import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import SessionLocal
from app.hub import hub
from app.models import ConversationMember, User
from app.redis_client import set_typing
from app.security import decode_token

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    token = ws.query_params.get("token")
    user_id = decode_token(token or "")
    if user_id is None:
        await ws.close(code=4401)
        return

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            await ws.close(code=4401)
            return

    await hub.connect(user_id, ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event_type = data.get("type")
            if event_type == "ping":
                await hub.heartbeat(user_id)
                await ws.send_text(json.dumps({"type": "pong"}))
            elif event_type == "typing":
                conversation_id = data.get("conversation_id")
                if not isinstance(conversation_id, int):
                    continue
                async with SessionLocal() as db:
                    member = (
                        await db.execute(
                            select(ConversationMember).where(
                                ConversationMember.conversation_id == conversation_id,
                                ConversationMember.user_id == user_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if member is None:
                        continue
                    member_ids = [
                        m.user_id
                        for m in (
                            await db.execute(
                                select(ConversationMember).where(
                                    ConversationMember.conversation_id == conversation_id
                                )
                            )
                        ).scalars().all()
                    ]
                is_typing = bool(data.get("is_typing", True))
                if is_typing:
                    await set_typing(conversation_id, user_id)
                await hub.send_to_users(
                    [mid for mid in member_ids if mid != user_id],
                    {
                        "type": "typing",
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "is_typing": is_typing,
                    },
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(user_id, ws)
