from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hub import hub
from app.models import ConversationMember, Message, Notification, User
from app.redis_client import is_online


async def notify_offline_members(db: AsyncSession, message: Message, sender_name: str) -> None:
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == message.conversation_id,
            ConversationMember.user_id != message.sender_id,
        )
    )
    members = result.scalars().all()
    preview = message.content.strip() or (message.file_name or "sent an attachment")
    body = f"{sender_name}: {preview[:140]}"
    offline_ids: list[int] = []
    for member in members:
        if await is_online(member.user_id):
            continue
        db.add(
            Notification(
                user_id=member.user_id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                body=body,
            )
        )
        offline_ids.append(member.user_id)
    if offline_ids:
        await db.commit()
        await hub.send_to_users(
            offline_ids,
            {
                "type": "notification",
                "conversation_id": message.conversation_id,
                "message_id": message.id,
                "body": body,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )


def serialize_message(message: Message, sender: User) -> dict:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_id": message.sender_id,
        "sender_username": sender.username,
        "sender_avatar": sender.avatar_url,
        "content": message.content,
        "message_type": message.message_type,
        "file_url": message.file_url,
        "file_name": message.file_name,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
