"""
Configuration Management
Loads from environment variables with defaults and validation.
"""

import os
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # OpenAI
    openai_api_key: str = ""

    # Deepgram
    deepgram_api_key: str = ""

    # Agent behaviour
    llm_model: str = "gpt-4o-mini"
    tts_voice: str = "alloy"
    greeting: str = "Hello! How can I help you today?"
    max_call_minutes: int = 30

    # Server
    webhook_base_url: str = ""
    port: int = 8080

    # Logging
    log_dir: str = "./logs"
    log_level: str = "INFO"
    json_logs: bool = True

    # Cost alerts
    cost_alert_threshold_usd: float = 5.0
    daily_budget_usd: float = 100.0


def load_config() -> AgentConfig:
    cfg = AgentConfig(
        livekit_url=os.environ.get("LIVEKIT_URL", ""),
        livekit_api_key=os.environ.get("LIVEKIT_API_KEY", ""),
        livekit_api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_phone_number=os.environ.get("TWILIO_PHONE_NUMBER", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        tts_voice=os.environ.get("TTS_VOICE", "alloy"),
        greeting=os.environ.get("AGENT_GREETING", "Hello! How can I help you today?"),
        webhook_base_url=os.environ.get("WEBHOOK_BASE_URL", ""),
        port=int(os.environ.get("PORT", "8080")),
        log_dir=os.environ.get("LOG_DIR", "./logs"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        json_logs=os.environ.get("JSON_LOGS", "true").lower() == "true",
        cost_alert_threshold_usd=float(os.environ.get("COST_ALERT_THRESHOLD", "5.0")),
        daily_budget_usd=float(os.environ.get("DAILY_BUDGET_USD", "100.0")),
    )

    required = {
        "LIVEKIT_URL": cfg.livekit_url,
        "LIVEKIT_API_KEY": cfg.livekit_api_key,
        "LIVEKIT_API_SECRET": cfg.livekit_api_secret,
        "TWILIO_ACCOUNT_SID": cfg.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": cfg.twilio_auth_token,
        "OPENAI_API_KEY": cfg.openai_api_key,
        "DEEPGRAM_API_KEY": cfg.deepgram_api_key,
        "WEBHOOK_BASE_URL": cfg.webhook_base_url,
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.warning(f"Missing env vars: {', '.join(missing)} — some features will be disabled")

    return cfg
