"""
LiveKit Voice AI Agent with Twilio SIP Trunk
Handles inbound/outbound calls with real-time STT → LLM → TTS pipeline
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
    llm,
    AgentSession,
)
from livekit.agents.voice import Agent
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
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    turn_count: int = 0
    total_tokens: int = 0
    transcript: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        end = self.ended_at or datetime.now(timezone.utc)
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

    def _parse_room_metadata(self, room_metadata: Optional[str]) -> dict:
        """Parse room metadata safely."""
        if not room_metadata:
            return {}
        try:
            return json.loads(room_metadata)
        except Exception:
            return {}

    def _handle_conversation_item(self, session: CallSession, event: Any):
        """Handle incoming conversation items and log user/assistant turns."""
        from livekit.agents.llm import ChatMessage
        item = event.item
        if not isinstance(item, ChatMessage):
            return
        
        text = item.text_content() or ""
        if not text.strip():
            return

        if item.role == "user":
            session.turn_count += 1
            session.transcript.append({
                "role": "user",
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": item.transcript_confidence or 1.0,
            })
            self.agent_logger.log_turn(session, role="user", text=text)
            logger.info(f"[{session.session_id}] USER: {text[:120]}")

        elif item.role == "assistant":
            # Estimate tokens for cost tracking (rough: 1 token ≈ 4 chars)
            est_tokens = len(text) // 4
            session.total_tokens += est_tokens

            session.transcript.append({
                "role": "assistant",
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "estimated_tokens": est_tokens,
            })
            self.cost_tracker.record_tts(characters=len(text), session_id=session.session_id)
            self.agent_logger.log_turn(session, role="assistant", text=text)
            logger.info(f"[{session.session_id}] AGENT: {text[:120]}")

    def _handle_function_calls(self, session: CallSession, event: Any):
        """Log structured tool call information."""
        for call in event.function_calls:
            self.agent_logger.log_function_call(
                session,
                function_name=call.name,
                arguments=call.arguments,
            )

    async def _generate_and_speak_greeting(self, session: CallSession, assistant: AgentSession, lm: openai.LLM):
        """Generate a dynamic greeting and say it to the user."""
        logger.info(f"[{session.session_id}] Generating dynamic greeting...")
        try:
            greeting_ctx = llm.ChatContext().append(
                role="system",
                text=self._build_system_prompt(session)
            ).append(
                role="user",
                text="Please generate the initial greeting for this call according to the policy. Speak directly to the rep. Do not include any other text."
            )
            
            greeting_response = await lm.chat(chat_ctx=greeting_ctx).collect()
            greeting_text = greeting_response.text
            
            # Record this turn in the transcript
            session.transcript.append({
                "role": "assistant",
                "text": greeting_text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "initial_greeting"
            })
            
            await assistant.say(greeting_text, allow_interruptions=True)
            logger.info(f"[{session.session_id}] Dynamic Greeting: {greeting_text}")
            
        except Exception as e:
            logger.exception(f"[{session.session_id}] Failed to generate dynamic greeting: {e}")
            fallback_greeting = "Hi there, I'm an AI assistant calling for a brief pipeline check. Does now work?"
            await assistant.say(fallback_greeting, allow_interruptions=True)

    async def entrypoint(self, ctx: JobContext):
        """Main entry point called by LiveKit Worker for each new call."""

        meta = self._parse_room_metadata(ctx.room.metadata)

        session = CallSession(
            call_sid=meta.get("call_sid") or ctx.room.name,
            phone_number=meta.get("from_number") or "direct_webrtc",
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
            temperature=0.3,
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

        assistant = AgentSession(
            vad=vad,
            stt=stt,
            llm=lm,
            tts=tts,
            tools=[fnc_ctx],
            allow_interruptions=True,
            min_consecutive_speech_delay=0.6,
        )

        agent = Agent(
            instructions=self._build_system_prompt(session),
            chat_ctx=initial_ctx,
        )

        # Wire up event handlers using v1.0 event models
        from livekit.agents.voice.events import ConversationItemAddedEvent, FunctionToolsExecutedEvent

        @assistant.on("conversation_item_added")
        def _on_conversation_item_added(event: ConversationItemAddedEvent):
            self._handle_conversation_item(session, event)

        @assistant.on("function_tools_executed")
        def _on_function_tools_executed(event: FunctionToolsExecutedEvent):
            self._handle_function_calls(session, event)

        # Start the session in the room
        await assistant.start(agent=agent, room=ctx.room)

        # Dynamic Greeting
        await self._generate_and_speak_greeting(session, assistant, lm)

        # Keep running until the room closes
        try:
            await ctx.room.run_until_disconnected()
        finally:
            session.ended_at = datetime.now(timezone.utc)
            await self._finalize_session(session)
    async def _finalize_session(self, session: CallSession):
        """Run evaluation and write final cost summary after call ends."""
        logger.info(f"[{session.session_id}] Call ended | Duration={session.duration_seconds:.1f}s | Turns={session.turn_count}")

        # Record call end metrics in the cost tracker
        self.cost_tracker.record_call_end(
            session_id=session.session_id,
            duration_seconds=session.duration_seconds,
        )

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
                logger.exception(f"[{session.session_id}] Evaluation failed: {e}")

        self._active_sessions.pop(session.session_id, None)


def create_agent_worker(config: dict) -> WorkerOptions:
    agent = VoiceAIAgent(config)
    return WorkerOptions(
        entrypoint_fnc=agent.entrypoint,
        worker_type="room",
        max_retry=3,
    )
