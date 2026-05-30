"""
Main Entrypoint
Starts the LiveKit agent worker directly.
"""

import logging
import os
import sys

from livekit.agents import cli

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.voice_agent import create_agent_worker
from config.settings import load_config
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


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
    logger.info(f"  Log Dir:      {config.log_dir}")
    logger.info("=" * 60)

    # Configure the LiveKit Agent Worker
    agent_config = {
        "llm_model": config.llm_model,
        "tts_voice": config.tts_voice,
        "greeting": config.greeting,
    }

    worker_options = create_agent_worker(agent_config)

    # Start LiveKit worker (this is blocking)
    cli.run_app(worker_options)


if __name__ == "__main__":
    main()
