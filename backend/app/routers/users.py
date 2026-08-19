from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.media import save_upload
from app.models import Notification, User
from app.redis_client import is_online, online_map
from app.schemas import NotificationOut, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_out(user: User, online: bool = False) -> UserOut:
    return UserOut.model_validate(user).model_copy(update={"online": online})


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    return _user_out(current, online=True)


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    url, _, _ = await save_upload(file, images_only=True)
    current.avatar_url = url
    await db.commit()
    await db.refresh(current)
    return _user_out(current, online=True)


@router.get("/lookup", response_model=UserOut)
async def lookup_user(
    username: str = Query(min_length=1, max_length=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(func.lower(User.username) == username.strip().lower()))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="That username is not registered")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="That is your own account")
    return _user_out(user, online=await is_online(user.id))


@router.get("/search", response_model=list[UserOut])
async def search_users(
    q: str = Query(min_length=1, max_length=50),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    needle = q.strip()
    result = await db.execute(
        select(User)
        .where(
            User.id != current.id,
            or_(User.username.ilike(f"%{needle}%"), User.email.ilike(f"%{needle}%")),
        )
        .limit(20)
    )
    users = result.scalars().all()
    status = await online_map([u.id for u in users])
    users = sorted(users, key=lambda u: (u.username.lower() != needle.lower(), u.username.lower()))
    return [_user_out(u, online=status.get(u.id, False)) for u in users]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_out(user, online=await is_online(user.id))


notify_router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@notify_router.get("", response_model=list[NotificationOut])
async def list_notifications(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@notify_router.post("/read")
async def mark_notifications_read(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(Notification.user_id == current.id, Notification.is_read.is_(False))
    )
    for n in result.scalars().all():
        n.is_read = True
    await db.commit()
    return {"ok": True}
