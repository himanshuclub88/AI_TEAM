# Minimal Single-User Multi-Agent Chat Backend

A small FastAPI backend for a single human administrator and multiple configurable AI agents.
Chats and tasks are persisted to JSON; messages are appended to JSONL files.

## Features

- Individual chats and shared group chats
- Configurable agents stored in `data/agents.json`
- Persistent chat metadata, tasks, and message history
- Triggered execution: a user message or task handoff can trigger relevant agents
- Agents communicate through chat messages
- One shared LLM adapter (`llm.py`) used by all agents
- Pydantic request/response schemas
- No frontend, authentication, database, queue, or always-running workers
