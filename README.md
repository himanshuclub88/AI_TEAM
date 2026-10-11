# AI Team core update: `agent.py` and `main.py`

This update introduces the first bounded multi-agent workflow while preserving the existing schemas, storage helpers, and shared LLM adapter interface.

## Install/update
Copy `agent.py` and `main.py` into your backend package, replacing the existing files. Keep your current `schemas.py`, `storage.py`, and `llm.py`.

## Behavior
- A message sent in an individual chat with the `manager` is routed through `process_user_message`.
- Ordinary messages trigger a normal Manager response.
- Basic software-build requests (for example, "build a calculator app") trigger a bounded workflow:
  1. Creates Research, Architecture, and Development chats.
  2. Runs the Researcher with a requirements/research task.
  3. passes the research result to the Architect.
  4. passes research and architecture context into the shared development group.
  5. runs Frontend Developer, Backend Developer, and Tester with initial assignments.
  6. posts a workflow summary back to the main Manager chat.
- Chats and messages are persisted through existing JSON/JSONL storage.
- `/chats` returns stored chat records including workflow metadata for later frontend grouping.

## Current limitations
- Workflow execution is synchronous; the HTTP request waits for the agent calls.
- This does not yet stream live updates to the frontend.
- Developer agents cannot write files or execute tests until explicit tools are added.
- Intent detection is a lightweight keyword check, not an LLM classifier.
- Agent execution is bounded to the predefined workflow; dynamic agent-to-agent discussion loops are not implemented yet.
- Since current schemas do not include `project_id`, the project association is stored as extra fields (`workflow_key`, `workflow_chat`) in chat JSON records.
