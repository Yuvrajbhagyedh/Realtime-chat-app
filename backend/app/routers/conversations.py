from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import get_current_user, require_member
from app.hub import hub
from app.media import save_upload
from app.models import Conversation, ConversationMember, Message, User
from app.redis_client import online_map
from app.schemas import ConversationOut, DirectCreate, GroupCreate, GroupMembersAdd, MemberOut, MessageOut

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


async def _to_out(db: AsyncSession, conv: Conversation, current_id: int) -> ConversationOut:
    members = conv.members
    user_ids = [m.user_id for m in members]
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()}
    presence = await online_map(user_ids)
    member_outs = [
        MemberOut(
            id=m.user_id,
            username=users[m.user_id].username if m.user_id in users else "unknown",
            avatar_url=users[m.user_id].avatar_url if m.user_id in users else None,
            online=presence.get(m.user_id, False),
            role=m.role,
            last_read_at=m.last_read_at,
        )
        for m in members
    ]
    last_q = await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(1)
    )
    last = last_q.scalar_one_or_none()
    last_out = None
    if last:
        sender = users.get(last.sender_id) or await db.get(User, last.sender_id)
        last_out = MessageOut(
            id=last.id,
            conversation_id=last.conversation_id,
            sender_id=last.sender_id,
            sender_username=sender.username if sender else "unknown",
            sender_avatar=sender.avatar_url if sender else None,
            content=last.content,
            message_type=last.message_type,
            file_url=last.file_url,
            file_name=last.file_name,
            created_at=last.created_at,
        )
    my_member = next(m for m in members if m.user_id == current_id)
    unread_q = select(func.count(Message.id)).where(
        Message.conversation_id == conv.id,
        Message.sender_id != current_id,
    )
    if my_member.last_read_at is not None:
        unread_q = unread_q.where(Message.created_at > my_member.last_read_at)
    unread = (await db.execute(unread_q)).scalar_one()
    return ConversationOut(
        id=conv.id,
        type=conv.type,
        name=conv.name,
        avatar_url=conv.avatar_url,
        created_at=conv.created_at,
        members=member_outs,
        last_message=last_out,
        unread_count=unread,
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .join(ConversationMember)
        .where(ConversationMember.user_id == current.id)
        .options(selectinload(Conversation.members))
        .order_by(Conversation.created_at.desc())
    )
    convos = result.scalars().unique().all()
    return [await _to_out(db, c, current.id) for c in convos]


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_member(conversation_id, current.id, db)
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id).options(selectinload(Conversation.members))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await _to_out(db, conv, current.id)


@router.post("/direct", response_model=ConversationOut)
async def create_direct(
    payload: DirectCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.user_id == current.id:
        raise HTTPException(status_code=400, detail="Cannot start a chat with yourself")
    other = await db.get(User, payload.user_id)
    if not other:
        raise HTTPException(status_code=404, detail="User not found")

    mine = select(ConversationMember.conversation_id).where(ConversationMember.user_id == current.id)
    theirs = select(ConversationMember.conversation_id).where(ConversationMember.user_id == payload.user_id)
    existing = await db.execute(
        select(Conversation)
        .where(Conversation.type == "direct", Conversation.id.in_(mine), Conversation.id.in_(theirs))
        .options(selectinload(Conversation.members))
    )
    found = existing.scalars().first()
    if found and len(found.members) == 2:
        return await _to_out(db, found, current.id)

    conv = Conversation(type="direct", name=None, created_by=current.id)
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            ConversationMember(conversation_id=conv.id, user_id=current.id, role="member"),
            ConversationMember(conversation_id=conv.id, user_id=other.id, role="member"),
        ]
    )
    await db.commit()
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv.id).options(selectinload(Conversation.members))
    )
    conv = result.scalar_one()
    out = await _to_out(db, conv, current.id)
    await hub.send_to_users(
        [current.id, other.id],
        {"type": "conversation.upsert", "conversation_id": conv.id},
    )
    return out


@router.post("/group", response_model=ConversationOut)
async def create_group(
    payload: GroupCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member_ids = list({*payload.member_ids, current.id})
    if not member_ids:
        raise HTTPException(status_code=400, detail="Pick at least one registered user")
    users = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
    if len(users) != len(member_ids):
        raise HTTPException(status_code=400, detail="You can only add people who already have an account")
    conv = Conversation(type="group", name=payload.name, created_by=current.id)
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            ConversationMember(
                conversation_id=conv.id,
                user_id=uid,
                role="admin" if uid == current.id else "member",
            )
            for uid in member_ids
        ]
    )
    await db.commit()
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv.id).options(selectinload(Conversation.members))
    )
    conv = result.scalar_one()
    await hub.send_to_users(member_ids, {"type": "conversation.upsert", "conversation_id": conv.id})
    return await _to_out(db, conv, current.id)


@router.post("/{conversation_id}/members", response_model=ConversationOut)
async def add_members(
    conversation_id: int,
    payload: GroupMembersAdd,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member = await require_member(conversation_id, current.id, db)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Can only add members to group chats")
    if member.role not in ("admin", "member"):
        raise HTTPException(status_code=403, detail="Not allowed to add members")
    ids = set(payload.member_ids)
    for name in payload.usernames:
        cleaned = name.strip()
        if not cleaned:
            continue
        found = (
            await db.execute(select(User).where(func.lower(User.username) == cleaned.lower()))
        ).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail=f"No registered user named “{cleaned}”")
        ids.add(found.id)
    if not ids:
        raise HTTPException(status_code=400, detail="Pick a registered user from search")
    existing = {
        m.user_id
        for m in (
            await db.execute(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id))
        ).scalars().all()
    }
    for uid in ids:
        if uid in existing:
            continue
        if await db.get(User, uid) is None:
            raise HTTPException(status_code=404, detail="That person does not have an account")
        db.add(ConversationMember(conversation_id=conversation_id, user_id=uid, role="member"))
        existing.add(uid)
    await db.commit()
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id).options(selectinload(Conversation.members))
    )
    conv = result.scalar_one()
    await hub.send_to_users(list(existing), {"type": "conversation.upsert", "conversation_id": conversation_id})
    return await _to_out(db, conv, current.id)


@router.post("/{conversation_id}/avatar", response_model=ConversationOut)
async def upload_group_avatar(
    conversation_id: int,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_member(conversation_id, current.id, db)
    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.type != "group":
        raise HTTPException(status_code=400, detail="Only group chats can have a group photo")
    url, _, _ = await save_upload(file, images_only=True)
    conv.avatar_url = url
    await db.commit()
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id).options(selectinload(Conversation.members))
    )
    conv = result.scalar_one()
    member_ids = [m.user_id for m in conv.members]
    await hub.send_to_users(member_ids, {"type": "conversation.upsert", "conversation_id": conversation_id})
    return await _to_out(db, conv, current.id)


@router.post("/{conversation_id}/read")
async def mark_read(
    conversation_id: int,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    member = await require_member(conversation_id, current.id, db)
    member.last_read_at = datetime.now(timezone.utc)
    await db.commit()
    member_ids = [
        m.user_id
        for m in (
            await db.execute(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id))
        ).scalars().all()
    ]
    await hub.send_to_users(
        member_ids,
        {
            "type": "read",
            "conversation_id": conversation_id,
            "user_id": current.id,
            "last_read_at": member.last_read_at.isoformat(),
        },
    )
    return {"ok": True, "last_read_at": member.last_read_at}
