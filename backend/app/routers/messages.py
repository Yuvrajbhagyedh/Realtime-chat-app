from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_member
from app.hub import hub
from app.media import save_upload
from app.models import ConversationMember, Message, User
from app.notifications import notify_offline_members, serialize_message
from app.schemas import MessageOut

router = APIRouter(prefix="/api/conversations", tags=["messages"])


def _message_out(message: Message, sender: User) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
        sender_username=sender.username,
        sender_avatar=sender.avatar_url,
        content=message.content,
        message_type=message.message_type,
        file_url=message.file_url,
        file_name=message.file_name,
        created_at=message.created_at,
    )


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def history(
    conversation_id: int,
    before_id: int | None = None,
    limit: int = Query(default=50, le=100),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_member(conversation_id, current.id, db)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    if before_id:
        stmt = stmt.where(Message.id < before_id)
    stmt = stmt.order_by(Message.id.desc()).limit(limit)
    messages = list((await db.execute(stmt)).scalars().all())
    messages.reverse()
    if not messages:
        return []
    sender_ids = {m.sender_id for m in messages}
    senders = {
        u.id: u
        for u in (await db.execute(select(User).where(User.id.in_(sender_ids)))).scalars().all()
    }
    return [_message_out(m, senders.get(m.sender_id) or current) for m in messages]


@router.post("/{conversation_id}/messages", response_model=MessageOut)
async def send_message(
    conversation_id: int,
    content: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_member(conversation_id, current.id, db)
    content = (content or "").strip()
    file_url = None
    file_name = None
    message_type = "text"

    if file is not None and file.filename:
        file_url, file_name, message_type = await save_upload(file)

    if not content and not file_url:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    message = Message(
        conversation_id=conversation_id,
        sender_id=current.id,
        content=content,
        message_type=message_type,
        file_url=file_url,
        file_name=file_name,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    payload = serialize_message(message, current)
    member_ids = [
        m.user_id
        for m in (
            await db.execute(select(ConversationMember).where(ConversationMember.conversation_id == conversation_id))
        ).scalars().all()
    ]
    await hub.send_to_users(member_ids, {"type": "message", "payload": payload})
    await notify_offline_members(db, message, current.username)
    return _message_out(message, current)
