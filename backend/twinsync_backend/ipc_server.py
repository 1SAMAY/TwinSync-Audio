from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .logging_config import configure_logging
from .service import TwinSyncService

LOGGER = logging.getLogger(__name__)


def success(request_id: Any, result: Any) -> str:
    return json.dumps({"id": request_id, "ok": True, "result": result}, separators=(",", ":"))


def failure(request_id: Any, exc: Exception) -> str:
    return json.dumps(
        {"id": request_id, "ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}},
        separators=(",", ":"),
    )


def serve(service: TwinSyncService | None = None) -> int:
    configure_logging()
    app = service or TwinSyncService()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = str(request["method"])
            params = request.get("params") or {}
            response = success(request_id, app.dispatch(method, params))
        except Exception as exc:
            LOGGER.exception("IPC request failed")
            response = failure(locals().get("request_id"), exc)
        print(response, flush=True)
    app.audio.stop()
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())

