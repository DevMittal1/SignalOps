"""
Cost Tracking & Monitoring
Tracks API costs per session and in aggregate:
  - OpenAI LLM (input/output tokens)
  - Deepgram STT (audio minutes)
  - OpenAI TTS (characters)
  - LiveKit (minutes)
  - Twilio (call minutes)
"""

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Pricing Constants (USD) ─────────────────────────────────────────────────
# Update these when providers change pricing.

PRICING = {
    "llm": {
        "gpt-4o-mini": {
            "input_per_1k_tokens": 0.00015,
            "output_per_1k_tokens": 0.00060,
        },
        "gpt-4o": {
            "input_per_1k_tokens": 0.0050,
            "output_per_1k_tokens": 0.0150,
        },
        "gpt-4-turbo": {
            "input_per_1k_tokens": 0.01,
            "output_per_1k_tokens": 0.03,
        },
    },
    "stt": {
        "deepgram-nova-2": {
            "per_minute": 0.0059,
        },
        "deepgram-nova-2-phonecall": {
            "per_minute": 0.0059,
        },
    },
    "tts": {
        "openai-tts-1": {
            "per_1k_chars": 0.015,
        },
        "openai-tts-1-hd": {
            "per_1k_chars": 0.030,
        },
    },
    "livekit": {
        "per_minute_per_participant": 0.003,
    },
}


@dataclass
class SessionCosts:
    session_id: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # LLM
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_model: str = "gpt-4o-mini"
    llm_cost_usd: float = 0.0

    # STT
    stt_audio_minutes: float = 0.0
    stt_model: str = "deepgram-nova-2-phonecall"
    stt_cost_usd: float = 0.0

    # TTS
    tts_characters: int = 0
    tts_model: str = "openai-tts-1"
    tts_cost_usd: float = 0.0

    # Infrastructure
    call_minutes: float = 0.0
    livekit_participants: int = 2
    livekit_cost_usd: float = 0.0

    total_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class CostTracker:
    """
    Thread-safe cost tracker with in-memory store and JSONL persistence.
    """

    def __init__(self, log_dir: str = "./logs"):
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionCosts] = {}
        self._cost_file = Path(log_dir) / "costs.jsonl"
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        self._daily_totals: dict[str, float] = defaultdict(float)
        self._alert_threshold_usd = 10.0   # alert if a single session exceeds this
        logger.info("CostTracker initialised")

    def _get_or_create(self, session_id: str) -> SessionCosts:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionCosts(session_id=session_id)
        return self._sessions[session_id]

    # ─── Recording ───────────────────────────────────────────────────────────

    def record_llm_usage(
        self,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = "gpt-4o-mini",
    ) -> None:
        with self._lock:
            s = self._get_or_create(session_id)
            s.llm_input_tokens += input_tokens
            s.llm_output_tokens += output_tokens
            s.llm_model = model

            pricing = PRICING["llm"].get(model, PRICING["llm"]["gpt-4o-mini"])
            cost = (
                input_tokens / 1000 * pricing["input_per_1k_tokens"]
                + output_tokens / 1000 * pricing["output_per_1k_tokens"]
            )
            s.llm_cost_usd += cost
            self._update_total(s)

    def record_stt(
        self,
        session_id: str,
        audio_seconds: float,
        model: str = "deepgram-nova-2-phonecall",
    ) -> None:
        with self._lock:
            s = self._get_or_create(session_id)
            minutes = audio_seconds / 60.0
            s.stt_audio_minutes += minutes
            s.stt_model = model

            pricing = PRICING["stt"].get(model, PRICING["stt"]["deepgram-nova-2"])
            s.stt_cost_usd += minutes * pricing["per_minute"]
            self._update_total(s)

    def record_tts(self, session_id: str, characters: int, model: str = "openai-tts-1") -> None:
        with self._lock:
            s = self._get_or_create(session_id)
            s.tts_characters += characters
            s.tts_model = model

            pricing = PRICING["tts"].get(model, PRICING["tts"]["openai-tts-1"])
            s.tts_cost_usd += characters / 1000 * pricing["per_1k_chars"]
            self._update_total(s)

    def record_call_end(
        self,
        session_id: str,
        duration_seconds: float,
        participants: int = 2,
    ) -> None:
        with self._lock:
            s = self._get_or_create(session_id)
            minutes = duration_seconds / 60.0
            s.call_minutes = minutes
            s.livekit_participants = participants

            # LiveKit cost
            s.livekit_cost_usd = minutes * participants * PRICING["livekit"]["per_minute_per_participant"]
            self._update_total(s)

    def _update_total(self, s: SessionCosts) -> None:
        s.total_cost_usd = (
            s.llm_cost_usd
            + s.stt_cost_usd
            + s.tts_cost_usd
            + s.livekit_cost_usd
        )
        if s.total_cost_usd > self._alert_threshold_usd:
            logger.warning(
                f"Cost alert: session {s.session_id} has exceeded ${self._alert_threshold_usd:.2f} "
                f"(current: ${s.total_cost_usd:.4f})"
            )

    # ─── Retrieval ────────────────────────────────────────────────────────────

    def get_session_summary(self, session_id: str) -> dict:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return {}
            summary = s.to_dict()
            summary["breakdown"] = {
                "llm_pct": round(s.llm_cost_usd / max(s.total_cost_usd, 0.000001) * 100, 1),
                "stt_pct": round(s.stt_cost_usd / max(s.total_cost_usd, 0.000001) * 100, 1),
                "tts_pct": round(s.tts_cost_usd / max(s.total_cost_usd, 0.000001) * 100, 1),
                "infra_pct": round(
                    s.livekit_cost_usd
                    / max(s.total_cost_usd, 0.000001) * 100, 1
                ),
            }
            return summary

    def get_aggregate_stats(self, hours: int = 24) -> dict:
        """Aggregate stats across all sessions in the last N hours."""
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            relevant = [
                s for s in self._sessions.values()
                if datetime.fromisoformat(s.started_at) >= cutoff
            ]

            if not relevant:
                return {"session_count": 0, "total_cost_usd": 0.0}

            total_cost = sum(s.total_cost_usd for s in relevant)
            total_minutes = sum(s.call_minutes for s in relevant)

            return {
                "window_hours": hours,
                "session_count": len(relevant),
                "total_cost_usd": round(total_cost, 4),
                "avg_cost_per_call_usd": round(total_cost / len(relevant), 4),
                "total_call_minutes": round(total_minutes, 1),
                "avg_call_minutes": round(total_minutes / len(relevant), 1),
                "total_llm_tokens": sum(s.llm_input_tokens + s.llm_output_tokens for s in relevant),
                "cost_breakdown": {
                    "llm_usd": round(sum(s.llm_cost_usd for s in relevant), 4),
                    "stt_usd": round(sum(s.stt_cost_usd for s in relevant), 4),
                    "tts_usd": round(sum(s.tts_cost_usd for s in relevant), 4),
                    "livekit_usd": round(sum(s.livekit_cost_usd for s in relevant), 4),
                },
            }

    def flush_session(self, session_id: str) -> None:
        """Persist session costs to disk and remove from memory."""
        with self._lock:
            s = self._sessions.pop(session_id, None)
            if s:
                date_key = s.started_at[:10]
                self._daily_totals[date_key] += s.total_cost_usd
                with open(self._cost_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(s.to_dict(), default=str) + "\n")
                logger.info(
                    f"Session cost flushed | id={session_id} | "
                    f"total=${s.total_cost_usd:.4f} | date={date_key} | "
                    f"day_total=${self._daily_totals[date_key]:.4f}"
                )

    def get_daily_totals(self) -> dict:
        with self._lock:
            return dict(self._daily_totals)

    def set_alert_threshold(self, usd: float) -> None:
        self._alert_threshold_usd = usd
