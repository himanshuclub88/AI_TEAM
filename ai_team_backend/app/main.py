from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import get_agent, process_user_message, respond_as_agent
from .schemas import (
    Agent, AgentCreate, Chat, ChatCreate, Message, MessageCreate,
    Task, TaskComplete, TaskCreate, TaskStatusUpdate, utc_now,
)
from .storage import (
    append_message, ensure_storage, read_json, read_messages, write_json,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage()
    if not read_json("agents.json", []):
        seed_agents = [
            Agent(id="manager", name="Manager", instructions="Coordinate the project team. For software-building requests, use the development workflow; for ordinary chat, answer directly.", model="default"),
            Agent(id="researcher", name="Researcher", instructions="Research requirements, compare options, and share concise findings that the Architect can use.", model="default"),
            Agent(id="architect", name="Architect", instructions="Turn requirements and research into a practical design, contracts, and acceptance criteria.", model="default"),
            Agent(id="frontend_developer", name="Frontend Developer", instructions="Plan and implement frontend work according to the agreed architecture. Be clear if execution tools are unavailable.", model="default"),
            Agent(id="backend_developer", name="Backend Developer", instructions="Plan and implement backend work according to the agreed architecture. Be clear if execution tools are unavailable.", model="default"),
            Agent(id="tester", name="Tester", instructions="Create test plans, inspect implementation reports, identify defects, and verify fixes when execution tools are available.", model="default"),
        ]
        write_json("agents.json", [agent.model_dump(mode="json") for agent in seed_agents])
    yield


app = FastAPI(title="AI Team Backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _save_chat(chat: Chat) -> Chat:
    chats = read_json("chats.json", [])
    chats.append(chat.model_dump(mode="json"))
    write_json("chats.json", chats)
    return chat


def _get_chat(chat_id: str) -> Chat | None:
    for raw in read_json("chats.json", []):
        if raw.get("id") == chat_id:
            return Chat.model_validate(raw)
    return None


def _save_task(task: Task) -> Task:
    tasks = read_json("tasks.json", [])
    tasks.append(task.model_dump(mode="json"))
    write_json("tasks.json", tasks)
    return task


def _get_task(task_id: str) -> Task | None:
    for raw in read_json("tasks.json", []):
        if raw.get("id") == task_id:
            return Task.model_validate(raw)
    return None


def _update_task(task: Task) -> Task:
    tasks = read_json("tasks.json", [])
    for index, raw in enumerate(tasks):
        if raw.get("id") == task.id:
            tasks[index] = task.model_dump(mode="json")
            write_json("tasks.json", tasks)
            return task
    raise HTTPException(404, "Task not found")


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-team-backend", "version": "0.2.0"}


@app.get("/agents", response_model=list[Agent])
def list_agents():
    return [Agent.model_validate(agent) for agent in read_json("agents.json", [])]


@app.post("/agents", response_model=Agent, status_code=201)
def create_agent(payload: AgentCreate):
    agents = read_json("agents.json", [])
    if any(agent["id"] == payload.id for agent in agents):
        raise HTTPException(409, "Agent ID already exists")
    agent = Agent(**payload.model_dump())
    agents.append(agent.model_dump(mode="json"))
    write_json("agents.json", agents)
    return agent


@app.get("/chats")
def list_chats():
    # Preserve workflow metadata used to group chats by project in later frontend work.
    return read_json("chats.json", [])


@app.post("/chats", response_model=Chat, status_code=201)
def create_chat(payload: ChatCreate):
    if not payload.participant_ids:
        raise HTTPException(422, "At least one agent participant is required")
    for agent_id in payload.participant_ids:
        agent = get_agent(agent_id)
        if not agent or not agent.enabled:
            raise HTTPException(422, f"Unknown or disabled agent: {agent_id}")
    if payload.chat_type == "individual" and len(payload.participant_ids) != 1:
        raise HTTPException(422, "Individual chats must have exactly one agent participant")
    chat = Chat(
        id=f"chat_{uuid4().hex[:12]}",
        title=payload.title,
        chat_type=payload.chat_type,
        participant_ids=payload.participant_ids,
    )
    return _save_chat(chat)


@app.get("/chats/{chat_id}", response_model=Chat)
def get_chat(chat_id: str):
    chat = _get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@app.get("/chats/{chat_id}/messages", response_model=list[Message])
def get_chat_messages(chat_id: str):
    if not _get_chat(chat_id):
        raise HTTPException(404, "Chat not found")
    return [Message.model_validate(message) for message in read_messages(chat_id)]


@app.post("/chats/{chat_id}/messages", response_model=list[Message])
def send_message(chat_id: str, payload: MessageCreate):
    chat = _get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    if payload.sender_id != "user":
        raise HTTPException(422, "Only the human administrator can post through this endpoint")

    target_ids = payload.target_agent_ids or chat.participant_ids
    for agent_id in target_ids:
        if agent_id not in chat.participant_ids:
            raise HTTPException(422, f"Agent {agent_id} is not a participant in this chat")

    user_message = Message(
        id=f"msg_{uuid4().hex[:12]}",
        chat_id=chat_id,
        sender_id="user",
        content=payload.content,
    )
    append_message(chat_id, user_message.model_dump(mode="json"))

    try:
        if chat.chat_type == "individual" and chat.participant_ids == ["manager"]:
            generated = process_user_message(chat, user_message)
        else:
            generated = []
            for agent_id in target_ids:
                agent = get_agent(agent_id)
                if agent and agent.enabled:
                    generated.append(respond_as_agent(agent, chat.id))
    except NotImplementedError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Agent execution failed: {exc}") from exc

    # Return newly generated messages; the frontend can reload canonical history.
    return [user_message, *generated]


@app.post("/tasks", response_model=Task, status_code=201)
def create_task(payload: TaskCreate):
    chat = _get_chat(payload.chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    agent = get_agent(payload.assigned_to)
    if not agent or not agent.enabled:
        raise HTTPException(422, "Unknown or disabled target agent")

    task = Task(
        id=f"task_{uuid4().hex[:12]}",
        title=payload.title,
        description=payload.description,
        chat_id=payload.chat_id,
        assigned_to=payload.assigned_to,
        created_by=payload.created_by,
        depends_on=payload.depends_on,
    )
    _save_task(task)
    append_message(payload.chat_id, Message(
        id=f"msg_{uuid4().hex[:12]}",
        chat_id=payload.chat_id,
        sender_id=payload.created_by,
        content=f"Task assigned to {agent.name}: {task.title}\n{task.description}",
        message_type="task_handoff",
        task_id=task.id,
        metadata={"recipient_ids": [agent.id]},
    ).model_dump(mode="json"))

    try:
        respond_as_agent(agent, payload.chat_id, task)
    except NotImplementedError as exc:
        raise HTTPException(503, str(exc)) from exc
    return task


@app.get("/tasks", response_model=list[Task])
def list_tasks():
    return [Task.model_validate(task) for task in read_json("tasks.json", [])]


@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: str):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@app.post("/tasks/{task_id}/accept", response_model=Task)
def accept_task(task_id: str, payload: TaskStatusUpdate):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "accepted"
    task.updated_at = utc_now()
    _update_task(task)
    append_message(task.chat_id, Message(
        id=f"msg_{uuid4().hex[:12]}",
        chat_id=task.chat_id,
        sender_id=task.assigned_to,
        content=payload.note or f"Accepted task: {task.title}",
        message_type="acknowledgement",
        task_id=task.id,
    ).model_dump(mode="json"))
    return task


@app.post("/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: str, payload: TaskComplete):
    task = _get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = "completed"
    task.result = payload.result
    task.updated_at = utc_now()
    _update_task(task)
    append_message(task.chat_id, Message(
        id=f"msg_{uuid4().hex[:12]}",
        chat_id=task.chat_id,
        sender_id=task.assigned_to,
        content=payload.result,
        message_type="task_result",
        task_id=task.id,
    ).model_dump(mode="json"))
    return task
