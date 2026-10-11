from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentCreate(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=8000)
    model: str = "default"
    enabled: bool = True


class Agent(AgentCreate):
    created_at: datetime = Field(default_factory=utc_now)


class ChatCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=160)
    chat_type: Literal["individual", "group"] = "individual"
    participant_ids: list[str] = Field(default_factory=lambda: ["manager"])
    # Individual chats should normally contain one bot; group chats can contain many.
    model_config = ConfigDict(extra="forbid")


class Chat(BaseModel):
    id: str
    title: str
    chat_type: Literal["individual", "group"]
    participant_ids: list[str]
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MessageCreate(BaseModel):
    sender_id: str = "user"
    content: str = Field(min_length=1, max_length=20000)
    # Optional override. If omitted, individual chats use their sole bot and group chats use all participants.
    target_agent_ids: list[str] | None = None


class Message(BaseModel):
    id: str
    chat_id: str
    sender_id: str
    content: str
    message_type: Literal["chat", "task_handoff", "acknowledgement", "task_result", "system"] = "chat"
    task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    chat_id: str
    assigned_to: str
    created_by: str = "user"
    depends_on: list[str] = Field(default_factory=list)


class Task(BaseModel):
    id: str
    title: str
    description: str
    chat_id: str
    assigned_to: str
    created_by: str
    status: Literal["assigned", "accepted", "in_progress", "blocked", "completed", "rejected"] = "assigned"
    depends_on: list[str] = Field(default_factory=list)
    result: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskStatusUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class TaskComplete(BaseModel):
    result: str = Field(min_length=1, max_length=20000)
