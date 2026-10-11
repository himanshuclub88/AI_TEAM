from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from . import llm
from .schemas import Agent, Chat, Message, Task, utc_now
from .storage import append_message, read_json, read_messages, write_json
from . import workspace


class GeneratedFile(BaseModel):
    path: str = Field(description="Safe relative path inside the project folder")
    content: str = Field(description="Complete UTF-8 file contents")


class DeveloperWorkProduct(BaseModel):
    reply: str = Field(description="Short status and implementation notes")
    files: list[GeneratedFile] = Field(default_factory=list, description="Files this agent created or updated")


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



def _update_task_record(task: Task, *, status: str, result: str | None = None) -> None:
    tasks = read_json("tasks.json", [])
    for index, raw in enumerate(tasks):
        if raw.get("id") == task.id:
            raw["status"] = status
            raw["result"] = result
            raw["updated_at"] = utc_now().isoformat()
            tasks[index] = raw
            write_json("tasks.json", tasks)
            return


def _run_workspace_agent(
    *,
    agent_id: str,
    chat: Chat,
    project_id: str,
    title: str,
    description: str,
    allowed_extensions: set[str],
    allowed_prefixes: tuple[str, ...] = (),
    run_checks: bool = False,
) -> tuple[Message, dict[str, Any] | None]:
    agent = get_agent(agent_id)
    if not agent or not agent.enabled:
        raise ValueError(f"Agent '{agent_id}' is missing or disabled")

    task = _create_task(chat.id, "manager", agent_id, title, description)
    _save_message(
        chat.id, "manager", f"Task assigned to {agent.name}: {title}\n{description}",
        "task_handoff", task.id, {"recipient_ids": [agent_id], "project_id": project_id},
    )
    role_rules = {
        "frontend_developer": "Create only frontend files such as index.html, style.css, and script.js. Do not create server.py unless explicitly required by the request.",
        "backend_developer": "Create backend files only when the requirements need a backend. If a static frontend is sufficient, return no files and explain why.",
        "tester": "Create tests only under tests/ (for example tests/test_app.py). Do not edit application source files. Then prepare the test plan.",
    }.get(agent_id, "Create only files that belong to your role.")
    system_prompt = (
        f"You are {agent.name}. Your instructions: {agent.instructions}\n"
        f"Project folder ID: {project_id}\n"
        f"Allowed file extensions: {', '.join(sorted(allowed_extensions))}.\n"
        f"Role restriction: {role_rules}\n"
        "Return complete file contents in the files field. Keep files focused and small. "
        "Use only relative file paths. Never include shell commands, run.cmd, batch scripts, "
        "executables, secrets, or files outside the project. Do not claim tests ran; the backend runner handles checks."
    )
    messages = _agent_context(agent, chat.id, task)
    messages.append({
        "role": "user",
        "content": (
            f"Project request: {description}\n"
            f"Current project files: {workspace.list_project_files(project_id)}\n"
            "Create or update the files needed for your assignment. Return a concise reply and complete file contents."
        ),
    })
    try:
        result = llm.generate_reply(
            system_prompt=system_prompt,
            messages=messages,
            response_model=DeveloperWorkProduct,
        )
        if isinstance(result, DeveloperWorkProduct):
            product = result
        elif isinstance(result, BaseModel):
            product = DeveloperWorkProduct.model_validate(result.model_dump())
        elif isinstance(result, dict):
            product = DeveloperWorkProduct.model_validate(result)
        else:
            raise ValueError("The LLM did not return a structured file work product")

        # The existing shared LLM adapter may fall back to putting raw model text in `reply`.
        # Recover a JSON work product when possible without changing that shared adapter.
        if not product.files:
            try:
                raw_payload = json.loads(product.reply)
                if isinstance(raw_payload, dict) and isinstance(raw_payload.get("files"), list):
                    product = DeveloperWorkProduct.model_validate(raw_payload)
            except (json.JSONDecodeError, ValueError):
                pass

        written: list[dict[str, Any]] = []
        for item in product.files:
            normalized = item.path.replace("\\", "/")
            if allowed_prefixes and not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
                raise ValueError(f"{agent.name} cannot write this path: {normalized}")
            written.append(workspace.write_project_file(
                project_id, normalized, item.content, allowed_extensions=allowed_extensions,
            ))

        check_result = workspace.run_project_checks(project_id) if run_checks else None
        reply = product.reply.strip() or f"{agent.name} completed its workspace task."
        if written:
            reply += "\n\nFiles written:\n" + "\n".join(f"- {item['path']} ({item['bytes']} bytes)" for item in written)
        else:
            reply += "\n\nNo files were needed for this assignment."
        if check_result is not None:
            reply += f"\n\nLocal checks: {check_result['status'].upper()}"
            for check in check_result["checks"]:
                reply += f"\n- {check['check']}: {check['status']}"
                if check.get("output"):
                    reply += f"\n{check['output'][-3000:]}"
        saved = _save_message(
            chat.id, agent.id, reply, "task_result", task.id,
            {"project_id": project_id, "files_written": written, "test_status": check_result["status"] if check_result else None},
        )
        _update_task_record(task, status="completed" if not check_result or check_result["status"] != "failed" else "blocked", result=reply)
        return saved, check_result
    except Exception as exc:
        error = f"{agent.name} workspace task failed: {type(exc).__name__}: {exc}"
        _save_message(chat.id, agent.id, error, "task_result", task.id, {"project_id": project_id, "error": True})
        _update_task_record(task, status="blocked", result=error)
        raise

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
    project = workspace.create_project(request)
    project_id = project["id"]

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
    _append_context(development_chat, "manager", "Local Playground", f"Project ID: {project_id}\nWorkspace path: {workspace.project_file_path(project_id, 'project.json').parent}\nDevelopers must write actual project files using the workspace tools.")

    development_results: list[Message] = []
    front_result, _ = _run_workspace_agent(
        agent_id="frontend_developer", chat=development_chat, project_id=project_id,
        title="Implement frontend",
        description=f"Build the frontend for this request: {request}\nArchitecture plan: {architecture_result.content}",
        allowed_extensions={".html", ".css", ".js", ".json", ".md", ".svg"},
    )
    development_results.append(front_result)

    back_result, _ = _run_workspace_agent(
        agent_id="backend_developer", chat=development_chat, project_id=project_id,
        title="Implement backend if required",
        description=f"Review the frontend and architecture. Implement only a necessary backend for: {request}\nArchitecture plan: {architecture_result.content}\nCurrent files: {workspace.list_project_files(project_id)}",
        allowed_extensions={".py", ".json", ".md", ".txt", ".toml", ".ini"},
    )
    development_results.append(back_result)

    tester_result, test_result = _run_workspace_agent(
        agent_id="tester", chat=development_chat, project_id=project_id,
        title="Create tests and run local checks",
        description=f"Inspect the actual files in project {project_id}. Create useful automated tests under tests/ where appropriate, then verify the project. Request: {request}\nCurrent files: {workspace.list_project_files(project_id)}",
        allowed_extensions={".py", ".md", ".txt"},
        allowed_prefixes=("tests/",),
        run_checks=True,
    )
    development_results.append(tester_result)
    run_cmd_path = workspace.generate_run_cmd(project_id)

    summary = (
        f"Project workflow started for: {request}\n\n"
        f"Research chat: {research_chat.id}\n"
        f"Architecture chat: {architecture_chat.id}\n"
        f"Development group: {development_chat.id}\n"
        f"Playground project: {project_id}\n"
        f"Project folder: {workspace.project_file_path(project_id, 'project.json').parent}\n"
        f"Run file: {run_cmd_path}\n"
        f"Local checks: {test_result['status'].upper()}\n\n"
        "Developer output has been written to the local Playground folder. The Tester ran the "
        "available fixed syntax/unit checks; review the check output before considering the project complete."
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
