from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from .offline_workflow import build_dashboard_snapshot, run_offline_workflow, store


ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "ui"


class DemoState:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}

    def create_run(self, prompt: str) -> dict[str, object]:
        run_id = str(uuid4())
        result = run_offline_workflow(prompt)
        self.runs[run_id] = {"prompt": prompt, "decisions": {}, "result": result}
        return {"run_id": run_id, "result": result}

    def resolve_approval(self, run_id: str, approval_id: str, approved: bool) -> dict[str, object] | None:
        run = self.runs.get(run_id)
        if not run:
            return None
        decisions = dict(run["decisions"])
        decisions[approval_id] = approved
        result = run_offline_workflow(str(run["prompt"]), decisions)
        run["decisions"] = decisions
        run["result"] = result
        return {"run_id": run_id, "result": result}

    def reset(self) -> None:
        self.runs.clear()
        store.reset_runtime()


APP_STATE = DemoState()


class ERPRequestHandler(BaseHTTPRequestHandler):
    server_version = "RevOpsERPDemo/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            self._json_response({"dashboard": build_dashboard_snapshot()})
            return
        if parsed.path == "/api/runtime":
            self._json_response({"dashboard": build_dashboard_snapshot()})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self._read_json()
        if parsed.path == "/api/run":
            prompt = str(payload.get("prompt", "")).strip()
            if not prompt:
                self._json_response({"error": "Prompt is required."}, status=HTTPStatus.BAD_REQUEST)
                return
            self._json_response(APP_STATE.create_run(prompt))
            return
        if parsed.path == "/api/approval":
            run_id = str(payload.get("run_id", "")).strip()
            approval_id = str(payload.get("approval_id", "")).strip()
            decision = str(payload.get("decision", "")).strip().lower()
            result = APP_STATE.resolve_approval(run_id, approval_id, decision == "approve")
            if result is None:
                self._json_response({"error": "Run not found."}, status=HTTPStatus.NOT_FOUND)
                return
            self._json_response(result)
            return
        if parsed.path == "/api/reset":
            APP_STATE.reset()
            self._json_response({"ok": True, "dashboard": build_dashboard_snapshot()})
            return
        self._json_response({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        if not body:
            return {}
        return json.loads(body)

    def _json_response(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_static(self, raw_path: str) -> None:
        path = raw_path if raw_path not in {"", "/"} else "/index.html"
        file_path = (UI_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(UI_DIR.resolve())) or not file_path.exists() or file_path.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content = file_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local ERP demo server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), ERPRequestHandler)
    print(f"ERP demo running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ERP demo server.")
    finally:
        server.server_close()
