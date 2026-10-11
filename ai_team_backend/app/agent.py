from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from . import llm
from .schemas import Agent, Chat, Message, Task, utc_now
from .storage import append_message, read_json, read_messages, write_json


class AgentDecision(BaseModel):
    """Structured response from an agent; handoffs are optional."""
    reply: str = Field(description="The message this agent sends to the chat")
    handoff_to: str | None = Field(
        default=None,
        description="Optional agent ID that should receive a follow-up task",
    )
    task_title: str | None = None
    task_description: str | None = None


def get_agent(agent_id: str) -> Agent | None:
    for raw in read_json("agents.json", []):
        if raw.get("id") == agent_id:
            return Agent.model_validate(raw)
    return None


def _save_message(
    chat_id: str,
    sender_id: str,
    content: str,
    message_type: str = "chat",
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    message = Message(
        id=f"msg_{uuid4().hex[:12]}",
        chat_id=chat_id,
        sender_id=sender_id,
        content=content,
        message_type=message_type,
        task_id=task_id,
        metadata=metadata or {},
    )
    append_message(chat_id, message.model_dump(mode="json"))
    _touch_chat(chat_id)
    return message


def _touch_chat(chat_id: str) -> None:
    chats = read_json("chats.json", [])
    for chat in chats:
        if chat.get("id") == chat_id:
            chat["updated_at"] = utc_now().isoformat()
            break
    write_json("chats.json", chats)


def _create_chat(title: str, chat_type: str, participant_ids: list[str]) -> Chat:
    """Create a persisted chat from inside the agent engine."""
    chats = read_json("chats.json", [])
    chat = Chat(
        id=f"chat_{uuid4().hex[:12]}",
        title=title,
        chat_type=chat_type,
        participant_ids=participant_ids,
    )
    chats.append(chat.model_dump(mode="json"))
    write_json("chats.json", chats)
    return chat


def _create_task(
    chat_id: str,
    created_by: str,
    assigned_to: str,
    title: str,
    description: str,
) -> Task:
    task = Task(
        id=f"task_{uuid4().hex[:12]}",
        title=title,
        description=description,
        chat_id=chat_id,
        created_by=created_by,
        assigned_to=assigned_to,
    )
    tasks = read_json("tasks.json", [])
    tasks.append(task.model_dump(mode="json"))
    write_json("tasks.json", tasks)
    return task


def _agent_context(agent: Agent, chat_id: str, task: Task | None = None) -> list[dict[str, str]]:
    history = [
        {
            "role": "assistant" if item.get("sender_id") != "user" else "user",
            "content": item.get("content", ""),
        }
        for item in read_messages(chat_id)[-30:]
    ]
    if task:
        history.append({
            "role": "user",
            "content": (
                f"Assigned task {task.id}: {task.title}\n"
                f"Description: {task.description}\n"
                "Work on this assignment. State assumptions, deliverables, blockers, and "
                "specific questions clearly. Do not claim code was executed unless it was."
            ),
        })
    return history


def respond_as_agent(
    agent: Agent,
    chat_id: str,
    task: Task | None = None,
    *,
    allow_handoff_trigger: bool = False,
) -> Message:
    """Run one agent once and persist its response in the specified chat."""
    system_prompt = (
        f"You are {agent.name} (agent id: {agent.id}).\n"
        f"Your instructions: {agent.instructions}\n\n"
        "You are a participant in a persistent AI team chat. Respond as this role, "
        "refer to relevant prior messages, and be specific about your deliverables. "
        "When work needs another agent, you may propose a handoff using the structured fields. "
        "Never claim that files were changed or tests were run unless tools actually did that."
    )
    result = llm.generate_reply(
        system_prompt=system_prompt,
        messages=_agent_context(agent, chat_id, task),
        response_model=AgentDecision,
    )

    if isinstance(result, AgentDecision):
        decision = result
    elif isinstance(result, BaseModel):
        decision = AgentDecision.model_validate(result.model_dump())
    elif isinstance(result, dict):
        decision = AgentDecision.model_validate(result)
    else:
        decision = AgentDecision(reply=str(result))

    saved = _save_message(
        chat_id,
        agent.id,
        decision.reply,
        "task_result" if task else "chat",
        task.id if task else None,
    )

    if allow_handoff_trigger and decision.handoff_to and decision.task_title and decision.task_description:
        target = get_agent(decision.handoff_to)
        if target and target.enabled and target.id != agent.id:
            new_task = _create_task(
                chat_id, agent.id, target.id,
                decision.task_title, decision.task_description,
            )
            _save_message(
                chat_id,
                agent.id,
                f"Task handoff to {target.name}: {new_task.title}\n{new_task.description}",
                "task_handoff",
                new_task.id,
                {"recipient_ids": [target.id]},
            )
            respond_as_agent(target, chat_id, new_task, allow_handoff_trigger=False)

    return saved


def _run_assigned_work(
    *,
    chat: Chat,
    agent_id: str,
    title: str,
    description: str,
    created_by: str = "manager",
) -> Message:
    agent = get_agent(agent_id)
    if not agent or not agent.enabled:
        raise ValueError(f"Agent '{agent_id}' is missing or disabled")

    task = _create_task(chat.id, created_by, agent_id, title, description)
    _save_message(
        chat.id,
        created_by,
        f"Task assigned to {agent.name}: {title}\n{description}",
        "task_handoff",
        task.id,
        {"recipient_ids": [agent_id]},
    )
    return respond_as_agent(agent, chat.id, task)


def _is_build_request(text: str) -> bool:
    """Lightweight first-pass intent routing; replace with a classifier later."""
    text = text.lower()
    action_words = ("build", "create", "develop", "implement", "make", "generate", "code")
    software_words = (
        "app", "application", "software", "website", "web site", "api",
        "backend", "frontend", "program", "tool", "platform", "project",
        "calculator", "chatbot", "dashboard",
    )
    return any(word in text for word in action_words) and any(word in text for word in software_words)


def _find_or_create_workflow_chat(
    title: str,
    chat_type: str,
    participant_ids: list[str],
    project_key: str,
) -> Chat:
    """Reuse workflow chats for the same project key; otherwise create them."""
    chats = read_json("chats.json", [])
    for raw in chats:
        if raw.get("workflow_key") == project_key and raw.get("title") == title:
            return Chat.model_validate(raw)

    chat = _create_chat(title, chat_type, participant_ids)
    # Existing Chat schema intentionally stays unchanged. Store workflow metadata alongside its record.
    chats = read_json("chats.json", [])
    for raw in chats:
        if raw.get("id") == chat.id:
            raw["workflow_key"] = project_key
            raw["workflow_chat"] = True
            break
    write_json("chats.json", chats)
    return chat


def _append_context(chat: Chat, sender_id: str, label: str, content: str) -> None:
    _save_message(
        chat.id,
        sender_id,
        f"{label}\n\n{content}",
        "system",
        metadata={"source": "workflow_context"},
    )


def run_development_workflow(main_chat: Chat, request: str) -> list[Message]:
    """
    Run a bounded, synchronous starter workflow:
    Manager -> Researcher -> Architect -> shared development group.

    It creates separate persistent chats. Agent execution is intentionally bounded
    so one request cannot trigger an unbounded chain of LLM calls.
    """
    project_key = f"{main_chat.id}:{uuid4().hex[:8]}"

    research_chat = _find_or_create_workflow_chat(
        f"Research · {request[:48]}",
        "group",
        ["manager", "researcher"],
        project_key,
    )
    architecture_chat = _find_or_create_workflow_chat(
        f"Architecture · {request[:48]}",
        "group",
        ["manager", "architect", "researcher"],
        project_key,
    )
    development_chat = _find_or_create_workflow_chat(
        f"Development · {request[:48]}",
        "group",
        ["manager", "architect", "frontend_developer", "backend_developer", "tester"],
        project_key,
    )

    _append_context(research_chat, "manager", "Project request", request)
    research_result = _run_assigned_work(
        chat=research_chat,
        agent_id="researcher",
        title="Research project requirements",
        description=(
            f"Research the following software request: {request}\n"
            "Identify core requirements, user flows, risks, and practical implementation options. "
            "Return findings that the Architect can use."
        ),
    )

    _append_context(architecture_chat, "manager", "Original request", request)
    _append_context(architecture_chat, "researcher", "Research findings", research_result.content)
    architecture_result = _run_assigned_work(
        chat=architecture_chat,
        agent_id="architect",
        title="Design the software architecture",
        description=(
            f"Design an implementation plan for: {request}\n"
            f"Research findings:\n{research_result.content}\n"
            "Specify components, contracts, file responsibilities, dependencies, and acceptance criteria."
        ),
    )

    _append_context(development_chat, "manager", "Original request", request)
    _append_context(development_chat, "researcher", "Research findings", research_result.content)
    _append_context(development_chat, "architect", "Architecture plan", architecture_result.content)

    developer_tasks = [
        (
            "frontend_developer",
            "Implement frontend",
            "Based on the architecture plan, define and implement the frontend work. If file-writing tools are unavailable, provide exact files and code needed; do not claim files were written.",
        ),
        (
            "backend_developer",
            "Implement backend",
            "Based on the architecture plan, define and implement the backend work. If file-writing tools are unavailable, provide exact files and code needed; do not claim files were written.",
        ),
        (
            "tester",
            "Prepare test plan",
            "Review the requirements and architecture, prepare acceptance tests, identify edge cases, and state what can be validated. Do not claim tests ran without execution tools.",
        ),
    ]

    development_results: list[Message] = []
    for agent_id, title, description in developer_tasks:
        result = _run_assigned_work(
            chat=development_chat,
            agent_id=agent_id,
            title=title,
            description=description + f"\n\nProject request: {request}",
        )
        development_results.append(result)

    summary = (
        f"Project workflow started for: {request}\n\n"
        f"Research chat: {research_chat.id}\n"
        f"Architecture chat: {architecture_chat.id}\n"
        f"Development group: {development_chat.id}\n\n"
        "Research and architecture have been generated, and the development group has received "
        "initial frontend, backend, and testing assignments. This starter coordinates agent "
        "messages and tasks; it does not yet provide file-system/code-execution tools to developers."
    )
    return [_save_message(main_chat.id, "manager", summary, "task_result")]


def process_user_message(chat: Chat, user_message: Message) -> list[Message]:
    """
    Main engine entry point for a new human message.
    Conversational messages go to the Manager. Software-build requests start the workflow.
    """
    manager = get_agent("manager")
    if not manager or not manager.enabled:
        raise ValueError("Manager agent is missing or disabled")

    if _is_build_request(user_message.content):
        return run_development_workflow(chat, user_message.content)

    return [respond_as_agent(manager, chat.id)]
