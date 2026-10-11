from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from . import llm, workspace
from .schemas import Agent, Chat, Message, Task, utc_now
from .storage import append_message, read_json, read_messages, write_json


# Each agent has one small, explicit Pydantic contract. The orchestrator uses
# these fields for routing; it does not inspect keywords in free-form replies.
class ManagerDecision(BaseModel):
    action: Literal["chat", "build"] = "chat"
    reply: str = ""
    project_request: str = ""


class ManagerClarification(BaseModel):
    action: Literal["answer", "ask_user"] = "answer"
    answer: str = ""
    question_for_user: str = ""


class ResearchResult(BaseModel):
    reply: str = "Research completed."
    requirements: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ArchitectureResult(BaseModel):
    reply: str = "Architecture prepared."
    platform: str = "web"
    summary: str = ""
    files: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    needs_backend: bool = False
    acceptance_criteria: list[str] = Field(default_factory=list)
    questions_for_manager: list[str] = Field(default_factory=list)


class GeneratedFile(BaseModel):
    path: str
    content: str


class DeveloperResult(BaseModel):
    status: Literal["ready", "needs_clarification", "blocked"] = "ready"
    reply: str = ""
    question_for_manager: str = ""
    files: list[GeneratedFile] = Field(default_factory=list)


class TesterResult(BaseModel):
    reply: str = "Testing review completed."
    files: list[GeneratedFile] = Field(default_factory=list)
    manual_checks: list[str] = Field(default_factory=list)
    known_limitations: list[str] = Field(default_factory=list)


def get_agent(agent_id: str) -> Agent | None:
    for item in read_json("agents.json", []):
        if item.get("id") == agent_id:
            return Agent.model_validate(item)
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
    for item in chats:
        if item.get("id") == chat_id:
            item["updated_at"] = utc_now().isoformat()
            break
    write_json("chats.json", chats)


def _create_chat(title: str, participant_ids: list[str]) -> Chat:
    chats = read_json("chats.json", [])
    chat = Chat(
        id=f"chat_{uuid4().hex[:12]}",
        title=title[:160],
        chat_type="group",
        participant_ids=participant_ids,
    )
    chats.append(chat.model_dump(mode="json"))
    write_json("chats.json", chats)
    return chat


def _create_task(chat_id: str, assigned_to: str, title: str, description: str) -> Task:
    task = Task(
        id=f"task_{uuid4().hex[:12]}",
        title=title,
        description=description,
        chat_id=chat_id,
        assigned_to=assigned_to,
        created_by="manager",
    )
    tasks = read_json("tasks.json", [])
    tasks.append(task.model_dump(mode="json"))
    write_json("tasks.json", tasks)
    return task


def _set_task(task: Task, status: str, result: str) -> None:
    tasks = read_json("tasks.json", [])
    for item in tasks:
        if item.get("id") == task.id:
            item["status"] = status
            item["result"] = result
            item["updated_at"] = utc_now().isoformat()
            break
    write_json("tasks.json", tasks)


def _history(chat_id: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user" if m.get("sender_id") == "user" else "assistant",
            "content": f"{m.get('sender_id', 'agent')}: {m.get('content', '')}",
        }
        for m in read_messages(chat_id)[-24:]
    ]


def _decode_result(result: Any, model: type[BaseModel]) -> BaseModel:
    """Validate a structured result, recovering JSON if the adapter wrapped it in reply."""
    if isinstance(result, model):
        value = result
    elif isinstance(result, BaseModel):
        value = model.model_validate(result.model_dump())
    elif isinstance(result, dict):
        value = model.model_validate(result)
    elif isinstance(result, str):
        value = model.model_validate_json(result)
    else:
        raise ValueError(f"Unsupported LLM result type: {type(result).__name__}")

    reply = getattr(value, "reply", "")
    if isinstance(reply, str) and reply.strip().startswith("{"):
        try:
            raw = json.loads(reply)
            if isinstance(raw, dict):
                return model.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return value


def _ask(
    agent_id: str,
    chat_id: str,
    system_prompt: str,
    user_prompt: str,
    response_model: type[BaseModel],
) -> BaseModel:
    agent = get_agent(agent_id)
    if not agent or not agent.enabled:
        raise ValueError(f"Agent '{agent_id}' is missing or disabled")
    result = llm.generate_reply(
        system_prompt=(
            f"You are {agent.name}, agent id {agent.id}.\n"
            f"Role instructions: {agent.instructions}\n\n"
            f"{system_prompt}\n\n"
            "Follow the Pydantic response schema exactly. Use sensible defaults rather than asking the user questions "
            "that another team agent can decide. Never claim files were written or commands were run unless true."
        ),
        messages=_history(chat_id) + [{"role": "user", "content": user_prompt}],
        response_model=response_model,
    )
    return _decode_result(result, response_model)


def _record_agent_result(chat: Chat, agent_id: str, task: Task, reply: str, metadata: dict[str, Any] | None = None) -> Message:
    message = _save_message(
        chat.id, agent_id, reply, "task_result", task.id, metadata or {},
    )
    _set_task(task, "completed", reply)
    return message


def _run_researcher(chat: Chat, request: str) -> ResearchResult:
    task = _create_task(chat.id, "researcher", "Research requirements", request)
    prompt = (
        f"Research this software request for the Architect: {request}\n"
        "Identify practical requirements, user flows, risks and assumptions. Be concise. "
        "Do not ask the user questions; use reasonable defaults and put any genuine blocker in risks."
    )
    try:
        result = _ask("researcher", chat.id, "Return research findings, requirements, assumptions and risks.", prompt, ResearchResult)
        _record_agent_result(chat, "researcher", task, result.reply, result.model_dump())
        return result
    except Exception as exc:
        _set_task(task, "blocked", str(exc))
        raise


def _run_architect(chat: Chat, request: str, research: ResearchResult) -> ArchitectureResult:
    task = _create_task(chat.id, "architect", "Design implementation", request)
    prompt = (
        f"User request: {request}\nResearch output:\n{research.model_dump_json(indent=2)}\n"
        "Choose a practical implementation. For a simple app, prefer the least complex stack. "
        "List exact files, features, and acceptance criteria. Set needs_backend=false for a static web app. "
        "Do not ask the user questions for choices you can reasonably decide."
    )
    try:
        result = _ask("architect", chat.id, "Create an implementation-ready design for the Developer and Tester.", prompt, ArchitectureResult)
        _record_agent_result(chat, "architect", task, result.reply, result.model_dump())
        return result
    except Exception as exc:
        _set_task(task, "blocked", str(exc))
        raise


def _write_agent_files(project_id: str, files: list[GeneratedFile], extensions: set[str], prefixes: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []
    for item in files:
        path = item.path.replace("\\", "/")
        if prefixes and not any(path.startswith(prefix) for prefix in prefixes):
            raise ValueError(f"File path not allowed for this role: {path}")
        written.append(workspace.write_project_file(project_id, path, item.content, allowed_extensions=extensions))
    return written


def _project_file_contents(project_id: str, max_total_chars: int = 24000) -> str:
    pieces: list[str] = []
    remaining = max_total_chars
    for item in workspace.list_project_files(project_id):
        path = item["path"]
        if path == "project.json" or remaining <= 0:
            continue
        try:
            content = workspace.read_project_file(project_id, path)
        except (OSError, ValueError):
            continue
        excerpt = content[:remaining]
        pieces.append(f"--- {path} ---\n{excerpt}")
        remaining -= len(excerpt)
    return "\n\n".join(pieces) or "(No source files have been created yet.)"


def _run_developer(
    chat: Chat,
    project_id: str,
    request: str,
    architecture: ArchitectureResult,
    agent_id: str = "frontend_developer",
    clarification: str = "",
) -> DeveloperResult:
    task = _create_task(chat.id, agent_id, "Implement application", request)
    prompt = (
        f"Original user request: {request}\n"
        f"Architecture contract:\n{architecture.model_dump_json(indent=2)}\n"
        f"Current files:\n{workspace.list_project_files(project_id)}\n"
        f"Manager clarification (if any): {clarification or 'None'}\n\n"
        "Implement the complete app now. Return every required file with full contents in `files`. "
        "For a static web app include at minimum index.html, style.css and script.js where appropriate, plus README.md. "
        "Do not return code inside reply; keep reply to a short status. Do not create project.json or run.cmd. "
        "Only return status=needs_clarification if a missing requirement truly prevents implementation; "
        "otherwise make a reasonable assumption and build."
    )
    try:
        result = _ask(
            agent_id, chat.id,
            "You are the implementation agent. Return status ready with real source files, or a single clear clarification question. "
            "Use paths relative to the project root. Do not merely describe code.",
            prompt, DeveloperResult,
        )
        assert isinstance(result, DeveloperResult)
        if result.status == "needs_clarification":
            _set_task(task, "blocked", result.question_for_manager or result.reply)
            _save_message(chat.id, agent_id, f"Needs manager clarification: {result.question_for_manager or result.reply}", "task_result", task.id, {"project_id": project_id, "needs_clarification": True})
            return result
        if result.status == "blocked":
            raise ValueError(result.reply or "Developer reported a blocker")
        if not result.files:
            raise ValueError("Developer returned no files. Task cannot be completed.")
        written = _write_agent_files(project_id, result.files, {".html", ".css", ".js", ".json", ".md", ".svg", ".txt"})
        if not any(Path(x["path"]).name.lower() == "index.html" for x in written) and not any(x["path"].lower() == "index.html" for x in workspace.list_project_files(project_id)):
            raise ValueError("Developer did not create index.html for the web application.")
        short = f"Implementation saved to Playground. Files: {', '.join(x['path'] for x in written)}"
        _record_agent_result(chat, agent_id, task, short, {"project_id": project_id, "files_written": written})
        return result
    except Exception as exc:
        _set_task(task, "blocked", str(exc))
        _save_message(chat.id, agent_id, f"Implementation failed: {type(exc).__name__}: {exc}", "task_result", task.id, {"project_id": project_id, "error": True})
        raise


def _run_tester(chat: Chat, project_id: str, request: str, architecture: ArchitectureResult) -> tuple[TesterResult, dict[str, Any]]:
    task = _create_task(chat.id, "tester", "Test implementation", request)
    prompt = (
        f"User request: {request}\nAcceptance criteria: {architecture.acceptance_criteria}\n"
        f"Actual project files:\n{_project_file_contents(project_id)}\n\n"
        "Review the real source code. Create useful automated tests or a TEST_REPORT.md under tests/ or project root. "
        "Do not modify app source files. Include concrete test cases, expected outcomes, and known limitations. "
        "Return any files in files with full contents; do not claim commands were run."
    )
    try:
        result = _ask("tester", chat.id, "Inspect source files and produce test artifacts. Be honest about what can be verified.", prompt, TesterResult)
        assert isinstance(result, TesterResult)
        written = _write_agent_files(project_id, result.files, {".py", ".md", ".txt"}, prefixes=("tests/",))
        checks = workspace.run_project_checks(project_id)
        report = {
            "project_id": project_id,
            "status": checks["status"],
            "checks": checks["checks"],
            "tester_summary": result.reply,
            "manual_checks": result.manual_checks,
            "known_limitations": result.known_limitations,
            "test_files_written": written,
        }
        (workspace.project_file_path(project_id, "test-results.txt", for_write=True)).write_text(json.dumps(report, indent=2), encoding="utf-8")
        status = "completed" if checks["status"] == "passed" else "blocked"
        summary = f"Tester report: {checks['status'].upper()}. {result.reply}\nChecks: " + ", ".join(f"{x['check']}={x['status']}" for x in checks["checks"])
        _record_agent_result(chat, "tester", task, summary, report)
        if status == "blocked":
            _set_task(task, "blocked", summary)
        return result, checks
    except Exception as exc:
        _set_task(task, "blocked", str(exc))
        _save_message(chat.id, "tester", f"Testing failed: {type(exc).__name__}: {exc}", "task_result", task.id, {"project_id": project_id, "error": True})
        raise


def _run_manager(user_chat: Chat, user_text: str) -> list[Message]:
    manager_task = None
    decision = _ask(
        "manager", user_chat.id,
        "You are the main orchestrator. For greetings, small talk, questions, and normal conversation choose action=chat and reply naturally. "
        "For requests to create, build, implement, or modify software choose action=build and rewrite the request clearly in project_request. "
        "Do not ask for platform, stack, or styling preferences for simple apps; use sensible defaults. You know the team has Researcher, Architect, Developer, and Tester agents.",
        f"User message: {user_text}", ManagerDecision,
    )
    assert isinstance(decision, ManagerDecision)
    # If the LLM adapter fell back to raw JSON text in reply, decode it in _decode_result.
    if decision.action == "chat":
        return [_save_message(user_chat.id, "manager", decision.reply or "How can I help?", "chat")]

    request = decision.project_request.strip() or user_text
    project = workspace.create_project(request)
    project_id = project["id"]
    key = f"{user_chat.id}:{project_id}"
    research_chat = _create_chat(f"Research · {request[:42]}", ["manager", "researcher"])
    architecture_chat = _create_chat(f"Architecture · {request[:42]}", ["manager", "researcher", "architect"])
    development_chat = _create_chat(f"Development · {request[:42]}", ["manager", "architect", "frontend_developer", "backend_developer", "tester"])
    for chat in (research_chat, architecture_chat, development_chat):
        raw = read_json("chats.json", [])
        for item in raw:
            if item.get("id") == chat.id:
                item["workflow_key"] = key
                item["workflow_chat"] = True
                item["project_id"] = project_id
        write_json("chats.json", raw)

    _save_message(research_chat.id, "manager", f"Project request\n{request}", "system", metadata={"project_id": project_id})
    research = _run_researcher(research_chat, request)
    _save_message(architecture_chat.id, "manager", f"Original request\n{request}", "system", metadata={"project_id": project_id})
    _save_message(architecture_chat.id, "researcher", f"Research findings\n{research.model_dump_json(indent=2)}", "system", metadata={"project_id": project_id})
    architecture = _run_architect(architecture_chat, request, research)
    if architecture.questions_for_manager:
        question = architecture.questions_for_manager[0]
        return [_save_message(user_chat.id, "manager", f"The team has one clarification before implementation: {question}", "chat", metadata={"project_id": project_id})]

    _save_message(development_chat.id, "manager", f"Original request\n{request}", "system", metadata={"project_id": project_id})
    _save_message(development_chat.id, "researcher", research.model_dump_json(indent=2), "system", metadata={"project_id": project_id})
    _save_message(development_chat.id, "architect", architecture.model_dump_json(indent=2), "system", metadata={"project_id": project_id})
    try:
        implementation = _run_developer(development_chat, project_id, request, architecture)
        if implementation.status == "needs_clarification":
            question = implementation.question_for_manager or implementation.reply
            resolution = _ask(
                "manager", user_chat.id,
                "Resolve the Developer's question using the user's request, research, and architecture. "
                "Prefer making a sensible decision. Choose ask_user only if a wrong assumption would materially change the requested outcome.",
                f"User request: {request}\nArchitecture: {architecture.model_dump_json(indent=2)}\nDeveloper question: {question}",
                ManagerClarification,
            )
            assert isinstance(resolution, ManagerClarification)
            if resolution.action == "ask_user":
                return [_save_message(user_chat.id, "manager", resolution.question_for_user or question, "chat", metadata={"project_id": project_id})]
            implementation = _run_developer(
                development_chat, project_id, request, architecture,
                clarification=resolution.answer or f"Manager decision: use the simplest reasonable default for: {question}",
            )
            if implementation.status != "ready":
                return [_save_message(user_chat.id, "manager", f"The project is paused because the Developer still needs clarification: {implementation.question_for_manager or implementation.reply}", "task_result", metadata={"project_id": project_id, "blocked": True})]
        run_file = workspace.generate_run_cmd(project_id)
        tester, checks = _run_tester(development_chat, project_id, request, architecture)
        file_list = ", ".join(item["path"] for item in workspace.list_project_files(project_id) if item["path"] != "project.json")
        summary = (
            f"Project created: {project['title']}\nProject ID: {project_id}\n"
            f"Folder: {workspace.project_file_path(project_id, 'project.json').parent}\n"
            f"Files: {file_list}\nRun: {run_file}\n"
            f"Tests: {checks['status'].upper()} (details in test-results.txt)."
        )
        return [_save_message(user_chat.id, "manager", summary, "task_result", metadata={"project_id": project_id, "test_status": checks["status"]})]
    except Exception as exc:
        return [_save_message(user_chat.id, "manager", f"I couldn't finish the project yet. Project folder: {workspace.project_file_path(project_id, 'project.json').parent}\nReason: {type(exc).__name__}: {exc}", "task_result", metadata={"project_id": project_id, "error": True})]


def process_user_message(chat: Chat, user_message: Message) -> list[Message]:
    """Entry point: Manager classifies with Pydantic, then orchestrates only when needed."""
    manager = get_agent("manager")
    if not manager or not manager.enabled:
        raise ValueError("Manager agent is missing or disabled")
    return _run_manager(chat, user_message.content)


def respond_as_agent(agent: Agent, chat_id: str, task: Task | None = None, *, allow_handoff_trigger: bool = False) -> Message:
    """Compatibility endpoint for direct agent chats and manual task calls."""
    result = _ask(
        agent.id, chat_id,
        "Reply directly in your assigned role. If a task is provided, work on that task.",
        f"Task: {task.title}\n{task.description}" if task else "Respond to the latest conversation message.",
        ManagerDecision,
    )
    assert isinstance(result, ManagerDecision)
    return _save_message(chat_id, agent.id, result.reply, "task_result" if task else "chat", task.id if task else None)
