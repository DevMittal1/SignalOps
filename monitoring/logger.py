"""
Structured Logging for Voice AI Agent
Writes JSON-structured logs for sessions, turns, costs, and evaluations.
Supports log rotation, multiple sinks (file + stdout), and log shipping.
"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ─── Formatters ─────────────────────────────────────────────────────────────

class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for log aggregators (Datadog, Loki, etc.)."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        # Attach structured context if present
        if hasattr(record, "context"):
            log_entry["context"] = record.context

        if record.exc_info:
            log_entry["exc"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


class HumanFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
        "RESET": "\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        reset = self.COLORS["RESET"]
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        msg = record.getMessage()

        ctx = ""
        if hasattr(record, "context"):
            ctx_str = "  ".join(f"{k}={v}" for k, v in record.context.items())
            ctx = f"  \033[2m{ctx_str}{reset}"

        return f"{color}[{record.levelname[0]}]{reset} {ts} {msg}{ctx}"


# ─── Logger Setup ────────────────────────────────────────────────────────────

def setup_logging(
    log_dir: str = "./logs",
    log_level: str = "INFO",
    json_logs: bool = True,
    max_bytes: int = 50 * 1024 * 1024,   # 50 MB
    backup_count: int = 7,
) -> None:
    """Configure root logger for the entire application."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console handler (human-readable)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(HumanFormatter())
    console.setLevel(level)
    root.addHandler(console)

    # Rotating file handler (JSON)
    json_file = logging.handlers.RotatingFileHandler(
        Path(log_dir) / "agent.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    json_file.setFormatter(JSONFormatter())
    json_file.setLevel(level)
    root.addHandler(json_file)

    # Separate error log
    error_file = logging.handlers.RotatingFileHandler(
        Path(log_dir) / "errors.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_file.setFormatter(JSONFormatter())
    error_file.setLevel(logging.ERROR)
    root.addHandler(error_file)

    # Suppress noisy third-party loggers
    for noisy in ["httpx", "httpcore", "websockets", "asyncio", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info("Logging configured", extra={"context": {"log_dir": log_dir, "level": log_level}})


# ─── Agent Logger ────────────────────────────────────────────────────────────

class AgentLogger:
    """
    High-level structured logger for call sessions.
    Writes machine-readable JSONL events to session-specific files.
    """

    def __init__(self, log_dir: str = "./logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._session_file = self.log_dir / "sessions.jsonl"
        self._transcript_dir = self.log_dir / "transcripts"
        self._transcript_dir.mkdir(exist_ok=True)
        self._logger = logging.getLogger("agent.session")

    def _write_event(self, file_path: Path, event: dict) -> None:
        event.setdefault("ts", datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def log_call_start(self, session: Any) -> None:
        event = {
            "event": "call_start",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "phone_number": session.phone_number,
            "started_at": session.started_at.isoformat(),
        }
        self._write_event(self._session_file, event)
        self._logger.info(
            "Call started",
            extra={"context": {"session": session.session_id, "sid": session.call_sid}},
        )

    def log_call_end(self, session: Any, cost_summary: Optional[dict] = None) -> None:
        event = {
            "event": "call_end",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "duration_seconds": session.duration_seconds,
            "turn_count": session.turn_count,
            "total_tokens": session.total_tokens,
            "cost_summary": cost_summary or {},
        }
        self._write_event(self._session_file, event)

        # Write full transcript
        transcript_file = self._transcript_dir / f"{session.session_id}.jsonl"
        self._write_event(transcript_file, {
            "event": "session_transcript",
            "session_id": session.session_id,
            "call_sid": session.call_sid,
            "turns": session.transcript,
        })

        self._logger.info(
            "Call ended",
            extra={"context": {
                "session": session.session_id,
                "duration": f"{session.duration_seconds:.1f}s",
                "turns": session.turn_count,
            }},
        )

    def log_turn(self, session: Any, role: str, text: str) -> None:
        event = {
            "event": "turn",
            "session_id": session.session_id,
            "turn": session.turn_count,
            "role": role,
            "text": text,
        }
        transcript_file = self._transcript_dir / f"{session.session_id}.jsonl"
        self._write_event(transcript_file, event)

    def log_function_call(self, session: Any, function_name: str, arguments: dict) -> None:
        event = {
            "event": "function_call",
            "session_id": session.session_id,
            "function": function_name,
            "args": arguments,
        }
        self._write_event(self._session_file, event)
        self._logger.info(
            f"Function call: {function_name}",
            extra={"context": {"session": session.session_id}},
        )

    def log_evaluation(self, session: Any, eval_result: dict) -> None:
        event = {
            "event": "evaluation",
            "session_id": session.session_id,
            **eval_result,
        }
        evals_file = self.log_dir / "evaluations.jsonl"
        self._write_event(evals_file, event)
        self._logger.info(
            "Evaluation complete",
            extra={"context": {
                "session": session.session_id,
                "score": eval_result.get("quality_score"),
                "sentiment": eval_result.get("sentiment"),
            }},
        )

    def log_error(self, session_id: str, error: Exception, context: Optional[dict] = None) -> None:
        event = {
            "event": "error",
            "session_id": session_id,
            "error_type": type(error).__name__,
            "error_msg": str(error),
            "context": context or {},
        }
        self._write_event(self._session_file, event)
        self._logging.exception(
            f"Error in session {session_id}: {error}",
            extra={"context": {"session": session_id}},
            exc_info=True,
        )
