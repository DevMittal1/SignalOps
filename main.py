"""
Main Entrypoint
Starts both the LiveKit agent worker and the Twilio webhook server.
"""

import asyncio
import logging
import os
import sys

import uvicorn
from livekit.agents import cli, WorkerOptions

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.voice_agent import create_agent_worker
from agent.twilio_bridge import app as webhook_app
from config.settings import load_config
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


async def run_webhook_server(config) -> None:
    """Run the FastAPI webhook server for Twilio callbacks."""
    server_config = uvicorn.Config(
        app=webhook_app,
        host="0.0.0.0",
        port=config.port,
        log_level=config.log_level.lower(),
        access_log=True,
    )
    server = uvicorn.Server(server_config)
    logger.info(f"Webhook server starting on port {config.port}")
    await server.serve()


def main():
    config = load_config()

    # Set up logging first
    setup_logging(
        log_dir=config.log_dir,
        log_level=config.log_level,
        json_logs=config.json_logs,
    )

    logger.info("=" * 60)
    logger.info("LiveKit Voice AI Agent Starting")
    logger.info(f"  LLM Model:    {config.llm_model}")
    logger.info(f"  TTS Voice:    {config.tts_voice}")
    logger.info(f"  LiveKit URL:  {config.livekit_url}")
    logger.info(f"  Webhook:      {config.webhook_base_url}")
    logger.info(f"  Log Dir:      {config.log_dir}")
    logger.info("=" * 60)

    # Run both: the LiveKit worker (blocking) + webhook server (background)
    agent_config = {
        "llm_model": config.llm_model,
        "tts_voice": config.tts_voice,
        "greeting": config.greeting,
    }

    worker_options = create_agent_worker(agent_config)

    # Start webhook server in background task
    loop = asyncio.get_event_loop()
    loop.create_task(run_webhook_server(config))

    # Start LiveKit worker (this is blocking)
    cli.run_app(worker_options)


if __name__ == "__main__":
    main()
