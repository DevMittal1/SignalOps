"""
LiveKit Voice AI Agent with Twilio SIP Trunk
Handles inbound/outbound calls with real-time STT → LLM → TTS pipeline
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero

from monitoring.cost_tracker import CostTracker
from monitoring.logger import AgentLogger
from evaluation.evaluator import ConversationEvaluator

from agent.tools import PipelineReviewTools
from agent.prompts import SYSTEM_PROMPT, STATIC_CONTEXT, get_dynamic_context

logger = logging.getLogger(__name__)


@dataclass
class CallSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    call_sid: Optional[str] = None          # Twilio Call SID
    phone_number: Optional[str] = None
    rep_id: str = "rep_204"                 # Default for demo
    deal_id: str = "deal_8931"              # Default for demo
    started_at: datetime = field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    turn_count: int = 0
    total_tokens: int = 0
    transcript: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or datetime.utcnow()
        return (end - self.started_at).total_seconds()


class VoiceAIAgent:
    """
    Pipeline Review Voice AI Agent:
    Uses sales context and sharp follow-ups to identify deal bottlenecks.
    """

    def __init__(self, config: dict):
        self.config = config
        self.cost_tracker = CostTracker()
        self.agent_logger = AgentLogger()
        self.evaluator = ConversationEvaluator()
        self._active_sessions: dict[str, CallSession] = {}

    def _build_system_prompt(self, session: CallSession) -> str:
        dynamic_ctx = get_dynamic_context(session.rep_id, session.deal_id)
        return (
            SYSTEM_PROMPT + 
            f"\nSession ID: {session.session_id}\n" +
            f"Call started: {session.started_at.strftime('%H:%M UTC')}\n" +
            dynamic_ctx
        )

    async def entrypoint(self, ctx: JobContext):
        """Main entry point called by LiveKit Worker for each new call."""

        # Extract metadata from room metadata
        room_meta = ctx.room.metadata or "{}"
        import json
        try:
            meta = json.loads(room_meta)
        except Exception:
            meta = {}

        session = CallSession(
            call_sid=meta.get("call_sid"),
            phone_number=meta.get("from_number"),
            rep_id=meta.get("rep_id", "rep_204"),
            deal_id=meta.get("deal_id", "deal_8931"),
            metadata=meta,
        )
        self._active_sessions[session.session_id] = session

        self.agent_logger.log_call_start(session)
        logger.info(f"[{session.session_id}] Pipeline Review Call started | Rep={session.rep_id} | Deal={session.deal_id}")

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        # STT — Deepgram Nova-2 (optimised for telephony)
        stt = deepgram.STT(
            model="nova-2-phonecall",
            language="en-US",
            smart_format=True,
            punctuate=True,
            interim_results=True,
        )

        # Function Context — Sharp pipeline tools
        fnc_ctx = PipelineReviewTools()

        # LLM — GPT-4o-mini (fast + cost-effective for voice)
        initial_ctx = llm.ChatContext().append(
            role="system",
            text=self._build_system_prompt(session),
        )
        lm = openai.LLM(
            model=self.config.get("llm_model", "gpt-4o-mini"),
            temperature=0.3, # Lower temperature for more factual consistency
        )

        # TTS — OpenAI with alloy voice (low latency)
        tts = openai.TTS(
            model="tts-1",
            voice=self.config.get("tts_voice", "alloy"),
            speed=1.0,
        )

        # VAD — Silero for precise end-of-speech detection
        vad = silero.VAD.load(
            min_silence_duration=0.4,
            min_speech_duration=0.1,
        )

        assistant = VoiceAssistant(
            vad=vad,
            stt=stt,
            llm=lm,
            tts=tts,
            chat_ctx=initial_ctx,
            fnc_ctx=fnc_ctx,
            allow_interruptions=True,
            interrupt_speech_duration=0.6,
            interrupt_min_words=3,
            preemptive_synthesis=True,
        )

        # Wire up event handlers
        assistant.on("user_speech_committed", self._on_user_speech(session))
        assistant.on("agent_speech_committed", self._on_agent_speech(session))
        assistant.on("function_calls_finished", self._on_function_calls(session))

        assistant.start(ctx.room)

        # Dynamic Greeting: Ask the LLM to generate the opening based on the context
        logger.info(f"[{session.session_id}] Generating dynamic greeting...")
        try:
            # We add a temporary instruction to generate the greeting
            greeting_ctx = llm.ChatContext().append(
                role="system",
                text=self._build_system_prompt(session)
            ).append(
                role="user",
                text="Please generate the initial greeting for this call according to the policy. Speak directly to the rep. Do not include any other text."
            )
            
            greeting_response = await lm.chat(chat_ctx=greeting_ctx)
            greeting_text = greeting_response.choices[0].message.content
            
            # Record this turn in the transcript
            session.transcript.append({
                "role": "assistant",
                "text": greeting_text,
                "timestamp": datetime.utcnow().isoformat(),
                "type": "initial_greeting"
            })
            
            await assistant.say(greeting_text, allow_interruptions=True)
            assistant.chat_ctx.append(role="assistant", text=greeting_text)
            logger.info(f"[{session.session_id}] Dynamic Greeting: {greeting_text}")
            
        except Exception as e:
            logger.error(f"[{session.session_id}] Failed to generate dynamic greeting: {e}")
            fallback_greeting = "Hi there, I'm an AI assistant calling for a brief pipeline check. Does now work?"
            await assistant.say(fallback_greeting, allow_interruptions=True)

        # Keep running until the room closes
        try:
            await ctx.room.run_until_disconnected()
        finally:
            session.ended_at = datetime.utcnow()
            await self._finalize_session(session)

    def _on_user_speech(self, session: CallSession):
        async def handler(event):
            text = event.alternatives[0].text if event.alternatives else ""
            if not text.strip():
                return

            session.turn_count += 1
            session.transcript.append({
                "role": "user",
                "text": text,
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": event.alternatives[0].confidence if event.alternatives else 0.0,
            })
            self.agent_logger.log_turn(session, role="user", text=text)
            logger.info(f"[{session.session_id}] USER: {text[:120]}")
        return handler

    def _on_agent_speech(self, session: CallSession):
        async def handler(event):
            text = event.text or ""
            if not text.strip():
                return

            # Estimate tokens for cost tracking (rough: 1 token ≈ 4 chars)
            est_tokens = len(text) // 4
            session.total_tokens += est_tokens

            session.transcript.append({
                "role": "assistant",
                "text": text,
                "timestamp": datetime.utcnow().isoformat(),
                "estimated_tokens": est_tokens,
            })
            self.cost_tracker.record_tts(characters=len(text), session_id=session.session_id)
            self.agent_logger.log_turn(session, role="assistant", text=text)
            logger.info(f"[{session.session_id}] AGENT: {text[:120]}")
        return handler

    def _on_function_calls(self, session: CallSession):
        async def handler(event):
            for call in event.calls:
                self.agent_logger.log_function_call(
                    session,
                    function_name=call.call_info.function_name,
                    arguments=call.call_info.arguments,
                )
        return handler

    async def _finalize_session(self, session: CallSession):
        """Run evaluation and write final cost summary after call ends."""
        logger.info(f"[{session.session_id}] Call ended | Duration={session.duration_seconds:.1f}s | Turns={session.turn_count}")

        # Cost summary
        cost_summary = self.cost_tracker.get_session_summary(session.session_id)
        self.agent_logger.log_call_end(session, cost_summary)

        # Quality evaluation (async, non-blocking to caller)
        if len(session.transcript) >= 2:
            try:
                eval_result = await self.evaluator.evaluate_async(session)
                self.agent_logger.log_evaluation(session, eval_result)
                logger.info(
                    f"[{session.session_id}] EVAL | "
                    f"quality={eval_result.get('quality_score', 0):.2f} | "
                    f"sentiment={eval_result.get('sentiment', 'unknown')}"
                )
            except Exception as e:
                logger.error(f"[{session.session_id}] Evaluation failed: {e}")

        self._active_sessions.pop(session.session_id, None)


def create_agent_worker(config: dict) -> WorkerOptions:
    agent = VoiceAIAgent(config)
    return WorkerOptions(
        entrypoint_fnc=agent.entrypoint,
        worker_type="room",
        max_retry=3,
    )
