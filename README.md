# AI Team — Local Playground update

This patch adds a local project workspace and basic Windows run/test support without changing the existing frontend or schemas.

## Files to install

Copy these three files into your existing backend package (the folder containing your current `agent.py`, `main.py`, `schemas.py`, `storage.py`, and `llm.py`):

- `app/agent.py` → replace your existing `agent.py`
- `app/main.py` → replace your existing `main.py`
- `app/workspace.py` → add this new file

Do **not** replace `schemas.py`, `storage.py`, `llm.py`, or your frontend.

## What it does

- Creates each generated project under `<backend-root>/playground/<project-id>/`.
- Lets the Frontend Developer return and write frontend source files; the Backend Developer can write backend files when needed.
- Lets the Tester create test files under `tests/` and run fixed checks from backend code.
- Runs Python syntax checks with the current Python interpreter and JavaScript syntax checks with `node --check` if Node.js is installed.
- Runs Python `unittest` discovery when `tests/test*.py` files exist.
- Generates `run.cmd` itself: it opens `index.html` for static web projects, or runs `python server.py` when `server.py` exists.
- Adds read-only APIs for the UI: `GET /projects`, `GET /projects/{project_id}/files`, and `GET /projects/{project_id}/file?path=index.html`.
- Marks research/architecture and workspace task records completed or blocked based on the result.

## Start the backend

Use the same command you already use for the backend. For example, from the folder above the `app` package:

```powershell
uvicorn app.main:app --reload
```

Use your actual package import path if it differs.

## Important limitations

- Agent calls are still synchronous. The HTTP request waits for the workflow and model calls.
- The file output is based on the LLM returning structured `files` entries. If the model fails to return valid structured output, that task is marked blocked.
- Checks are intentionally fixed in code; the API does not accept arbitrary shell commands.
- Python unit tests execute Python code on your Windows machine. Generated code is not sandboxed, so inspect generated files before running projects you do not trust.
- The generated `run.cmd` is a convenience launcher, not a security boundary. Double-click it only for projects you trust.
- Static syntax checks do not prove the app works. The Tester must create meaningful tests, and the user should review the output.
- The API endpoints added here are read-only for project browsing. File writes and test execution are invoked from the backend workflow, not exposed as unrestricted HTTP commands.
- No deployment to an external host is included yet.

## Quick verification after installation

1. Start the backend and open `/docs`.
2. Send a build request in a Manager chat, such as `Build me a calculator app`.
3. Check `GET /projects` for the new project ID.
4. Check `GET /projects/<project-id>/files` for generated files.
5. Inspect `playground/<project-id>/run.cmd` before double-clicking it.
6. Review the Development chat for written file names and the Tester check results.
