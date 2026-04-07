from __future__ import annotations

from functools import lru_cache
import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_PATH = DATA_DIR / "mock_crm.json"
OUTPUT_DIR = DATA_DIR / "runtime"
RUNTIME_DB = OUTPUT_DIR / "runtime_store.json"


def _empty_runtime_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        "tasks": [],
        "emails": [],
        "notes": [],
        "discount_requests": [],
    }


@lru_cache(maxsize=8)
def _read_json_file(path: str, mtime_ns: int) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


class RuntimeStore:
    """Tiny JSON-backed store for demo side effects."""

    def __init__(self, seed_path: Path = SEED_PATH, runtime_path: Path = RUNTIME_DB) -> None:
        self.seed_path = seed_path
        self.runtime_path = runtime_path
        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.runtime_path.exists():
            self.runtime_path.write_text(json.dumps(_empty_runtime_payload(), indent=2))

    def _read_seed(self) -> dict[str, Any]:
        return _read_json_file(str(self.seed_path), self.seed_path.stat().st_mtime_ns)

    def _read_runtime(self) -> dict[str, Any]:
        return _read_json_file(str(self.runtime_path), self.runtime_path.stat().st_mtime_ns)

    def _write_runtime(self, payload: dict[str, Any]) -> None:
        self.runtime_path.write_text(json.dumps(payload, indent=2))
        _read_json_file.cache_clear()

    def seed_data(self) -> dict[str, Any]:
        return self._read_seed()

    def runtime_data(self) -> dict[str, Any]:
        return self._read_runtime()

    def reset_runtime(self) -> None:
        self._write_runtime(_empty_runtime_payload())

    def find_account(self, account_name: str) -> dict[str, Any] | None:
        name = account_name.casefold()
        for account in self._read_seed()["accounts"]:
            if account["name"].casefold() == name:
                return account
        return None

    def find_lead(self, account_name: str) -> dict[str, Any] | None:
        name = account_name.casefold()
        for lead in self._read_seed()["leads"]:
            if lead["account_name"].casefold() == name:
                return lead
        return None

    def find_deal(self, account_name: str) -> dict[str, Any] | None:
        name = account_name.casefold()
        for deal in self._read_seed()["deals"]:
            if deal["account_name"].casefold() == name:
                return deal
        return None

    def list_campaigns(self) -> list[dict[str, Any]]:
        return self._read_seed()["campaigns"]

    def add_task(self, *, account_name: str, owner: str, due_date: str, task: str) -> dict[str, Any]:
        runtime = self._read_runtime()
        task_record = {
            "task_id": f"task_{len(runtime['tasks']) + 1:04d}",
            "account_name": account_name,
            "owner": owner,
            "due_date": due_date,
            "task": task,
            "created_on": date.today().isoformat(),
        }
        runtime["tasks"].append(task_record)
        self._write_runtime(runtime)
        return task_record

    def add_note(self, *, account_name: str, note: str, author: str = "agent") -> dict[str, Any]:
        runtime = self._read_runtime()
        note_record = {
            "note_id": f"note_{len(runtime['notes']) + 1:04d}",
            "account_name": account_name,
            "note": note,
            "author": author,
            "created_on": date.today().isoformat(),
        }
        runtime["notes"].append(note_record)
        self._write_runtime(runtime)
        return note_record

    def add_email(
        self,
        *,
        account_name: str,
        recipient: str,
        subject: str,
        body: str,
        approved: bool,
    ) -> dict[str, Any]:
        runtime = self._read_runtime()
        email_record = {
            "email_id": f"email_{len(runtime['emails']) + 1:04d}",
            "account_name": account_name,
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "approved": approved,
            "created_on": date.today().isoformat(),
        }
        runtime["emails"].append(email_record)
        self._write_runtime(runtime)
        return email_record

    def add_discount_request(
        self,
        *,
        account_name: str,
        percent: int,
        reason: str,
        submitted_by: str,
    ) -> dict[str, Any]:
        runtime = self._read_runtime()
        request_record = {
            "request_id": f"disc_{len(runtime['discount_requests']) + 1:04d}",
            "account_name": account_name,
            "percent": percent,
            "reason": reason,
            "submitted_by": submitted_by,
            "status": "submitted",
            "created_on": date.today().isoformat(),
        }
        runtime["discount_requests"].append(request_record)
        self._write_runtime(runtime)
        return request_record
