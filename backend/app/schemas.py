from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    avatar_url: str | None = None
    created_at: datetime
    online: bool = False

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MemberOut(BaseModel):
    id: int
    username: str
    avatar_url: str | None = None
    online: bool = False
    role: str = "member"
    last_read_at: datetime | None = None


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    sender_username: str
    sender_avatar: str | None = None
    content: str
    message_type: str
    file_url: str | None
    file_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    type: str
    name: str | None
    avatar_url: str | None = None
    created_at: datetime
    members: list[MemberOut]
    last_message: MessageOut | None = None
    unread_count: int = 0


class DirectCreate(BaseModel):
    user_id: int


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_ids: list[int] = Field(default_factory=list)


class GroupMembersAdd(BaseModel):
    member_ids: list[int] = Field(default_factory=list)
    usernames: list[str] = Field(default_factory=list)


class MessageCreate(BaseModel):
    content: str = Field(default="", max_length=8000)


class NotificationOut(BaseModel):
    id: int
    conversation_id: int
    message_id: int
    body: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
