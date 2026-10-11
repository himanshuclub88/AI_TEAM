import json
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MESSAGES_DIR = DATA_DIR / "messages"
_LOCK = threading.RLock()


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    for name, default in (
        ("agents.json", []),
        ("chats.json", []),
        ("tasks.json", []),
        ("llm_calls.json", []),
    ):
        path = DATA_DIR / name
        if not path.exists():
            write_json(name, default)


def read_json(name: str, default: Any = None) -> Any:
    path = DATA_DIR / name
    with _LOCK:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in {path}") from exc


def write_json(name: str, data: Any) -> None:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temp_path.replace(path)


def message_path(chat_id: str) -> Path:
    # Chat IDs are generated internally, but still restrict path characters.
    safe_id = "".join(ch for ch in chat_id if ch.isalnum() or ch in "-_")
    if not safe_id or safe_id != chat_id:
        raise ValueError("Invalid chat ID")
    return MESSAGES_DIR / f"{safe_id}.jsonl"


def append_message(chat_id: str, message: dict[str, Any]) -> None:
    path = message_path(chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")


def read_messages(chat_id: str) -> list[dict[str, Any]]:
    path = message_path(chat_id)
    with _LOCK:
        if not path.exists():
            return []
        rows = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSONL at {path}:{line_number}") from exc
        return rows


def update_record(filename: str, record_id: str, updated: dict[str, Any]) -> dict[str, Any] | None:
    with _LOCK:
        records = read_json(filename, [])
        for index, record in enumerate(records):
            if record.get("id") == record_id:
                records[index] = updated
                write_json(filename, records)
                return updated
    return None


def append_json_record(name: str, record: dict[str, Any]) -> dict[str, Any]:
    """Append one record to a JSON array while holding the storage lock."""
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        if path.exists():
            try:
                records = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON in {path}") from exc
        else:
            records = []
        if not isinstance(records, list):
            raise RuntimeError(f"Expected a JSON array in {path}")
        records.append(record)
        write_json(name, records)
    return record
