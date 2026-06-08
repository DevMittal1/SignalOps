"""
LiveKit Voice AI Agent with Twilio SIP Trunk
Handles inbound/outbound calls with real-time STT → LLM → TTS pipeline
"""

import asyncio
import json
import logging
import time
import uuid
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from pymongo import MongoClient
from bson import ObjectId

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
    AgentSession,
)
from livekit.agents.voice import Agent
from livekit.plugins import deepgram, google, openai, silero

from monitoring.cost_tracker import CostTracker
from monitoring.logger import AgentLogger
from evaluation.evaluator import ConversationEvaluator

from agent.tools import PipelineReviewTools
from agent.prompts import SYSTEM_PROMPT, STATIC_CONTEXT, get_dynamic_context

logger = logging.getLogger(__name__)

PUSH_OP = "$push"


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
    tools_called: list = field(default_factory=list)
    actions_taken: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    room: Optional[rtc.Room] = None         # LiveKit Room reference

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
        self._background_tasks = set()

        # MongoDB Connection
        self.db_connected = False
        self.db = None
        mongodb_uri = os.environ.get("MONGODB_URI", "")
        if mongodb_uri:
            try:
                client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=3000)
                client.admin.command('ping')
                self.db = client['signalops']
                self.db_connected = True
                logger.info("Voice AI Agent successfully connected to MongoDB Atlas")
            except Exception as e:
                logging.exception(f"Voice AI Agent failed to connect to MongoDB: {e}")

    def _build_system_prompt(self, session: CallSession) -> str:
        dynamic_ctx = get_dynamic_context(session.rep_id, session.deal_id)
        crm_ctx = self._get_crm_context_for_prompt(session.deal_id)
        return (
            SYSTEM_PROMPT + 
            f"\nSession ID: {session.session_id}\n" +
            f"Call started: {session.started_at.strftime('%H:%M UTC')}\n" +
            dynamic_ctx +
            crm_ctx
        )

    def _serialize_db_value(self, value: Any) -> Any:
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, list):
            return [self._serialize_db_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize_db_value(item) for key, item in value.items()}
        return value

    def _get_deal(self, deal_id: str) -> Optional[dict]:
        if not self.db_connected or self.db is None:
            return None
        deal = self.db["deals"].find_one({"_id": deal_id})
        if not deal:
            try:
                deal = self.db["deals"].find_one({"_id": ObjectId(deal_id)})
            except Exception:
                deal = None
        return self._serialize_db_value(deal) if deal else None

    def _get_crm_context_for_prompt(self, deal_id: str) -> str:
        deal = self._get_deal(deal_id)
        if not deal:
            return ""

        prompt_deal = {
            "deal_id": deal.get("_id"),
            "account_name": deal.get("account_name", deal.get("name")),
            "opportunity_name": deal.get("name"),
            "amount": deal.get("amount"),
            "stage": deal.get("stage"),
            "close_date": deal.get("close_date"),
            "priority": deal.get("priority"),
            "health_score": deal.get("health_score"),
            "days_in_stage": deal.get("days_in_stage"),
            "close_date_changes_90d": deal.get("close_date_changes_90d"),
            "risk_flags": deal.get("risk_flags", []),
            "next_best_actions": deal.get("next_best_actions", []),
            "stakeholders": deal.get("stakeholders", {}),
            "activity_health": deal.get("activity_health", {}),
            "dependencies": deal.get("dependencies", []),
            "last_customer_interaction": deal.get("last_customer_interaction", {}),
            "open_tickets": [ticket for ticket in deal.get("tickets", []) if ticket.get("status") == "open"][:5],
        }
        return "\nLive CRM Context For This Selected Deal:\n" + json.dumps(prompt_deal, indent=2) + "\n"

    def _create_task(self, coro):
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

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
        
        text = item.text_content or ""
        if not text.strip():
            return

        if item.role == "user":
            session.turn_count += 1
            session.transcript.append({
                "role": "user",
                "text": text,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "confidence": getattr(item, "transcript_confidence", 1.0),
            })
            self.agent_logger.log_turn(session, role="user", text=text)
            logger.info(f"[{session.session_id}] USER: {text[:120]}")
            
            # Broadcast user transcript to frontend
            if session.room:
                payload = json.dumps({
                    "type": "TRANSCRIPT",
                    "role": "user",
                    "text": text
                })
                self._create_task(session.room.local_participant.publish_data(payload))

            # Database persistence for transcript
            if self.db_connected and self.db is not None:
                try:
                    self.db['deals'].update_one(
                        {"_id": session.deal_id},
                        {PUSH_OP: {
                            "transcript": {
                                "speaker": "user",
                                "text": text,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        }}
                    )
                except Exception as e:
                    logging.exception(f"Failed to persist transcript to db: {e}")

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

            # Broadcast agent transcript to frontend
            if session.room:
                payload = json.dumps({
                    "type": "TRANSCRIPT",
                    "role": "assistant",
                    "text": text
                })
                self._create_task(session.room.local_participant.publish_data(payload))

            # Database persistence for transcript
            if self.db_connected and self.db is not None:
                try:
                    self.db['deals'].update_one(
                        {"_id": session.deal_id},
                        {PUSH_OP: {
                            "transcript": {
                                "speaker": "assistant",
                                "text": text,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        }}
                    )
                except Exception as e:
                    logging.exception(f"Failed to persist transcript to db: {e}")

    def _handle_function_calls(self, session: CallSession, event: Any):
        """Log structured tool call information."""
        for call in event.function_calls:
            self.agent_logger.log_function_call(
                session,
                function_name=call.name,
                arguments=call.arguments,
            )
            # Broadcast tool execution event to frontend
            try:
                args_dict = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
            except Exception:
                args_dict = call.arguments

            if session.room:
                payload = json.dumps({
                    "type": "TOOL_EXECUTION",
                    "function": call.name,
                    "arguments": args_dict
                })
                self._create_task(session.room.local_participant.publish_data(payload))

            session.tools_called.append({
                "function": call.name,
                "arguments": args_dict,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            # Database persistence
            if call.name == "append_call_fact":
                try:
                    self._db_append_fact(
                        session.deal_id,
                        args_dict.get("fact_type"),
                        args_dict.get("value"),
                        float(args_dict.get("confidence", 1.0))
                    )
                    session.actions_taken.append({
                        "description": f"Added fact [{args_dict.get('fact_type')}]: {args_dict.get('value')}",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except Exception as e:
                    logging.exception(f"Failed to persist fact to db: {e}")
            elif call.name == "save_call_summary":
                try:
                    self._db_save_summary(session.deal_id, args_dict)
                    session.actions_taken.append({
                        "description": f"Saved call summary: {args_dict.get('next_steps', 'No next steps specified')}",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    # Auto terminate the call
                    if session.room:
                        logger.info(f"[{session.session_id}] Auto-terminating call after summary.")
                        self._create_task(session.room.disconnect())
                except Exception as e:
                    logging.exception(f"Failed to persist summary to db: {e}")

    def _db_append_fact(self, deal_id: str, fact_type: str, value: str, confidence: float):
        if not self.db_connected or self.db is None:
            return
        try:
            deals_coll = self.db['deals']
            fact_doc = {
                "type": fact_type,
                "value": value,
                "confidence": confidence,
                "timestamp": time.time()
            }
            # Append to facts array
            deals_coll.update_one(
                {"_id": deal_id},
                {PUSH_OP: {
                    "facts": fact_doc,
                    "events": {
                        "type": "objection_flagged" if fact_type == "blocker_candidate" else "deal_updated",
                        "description": f"AI logged fact: {fact_type} = '{value}'",
                        "timestamp": time.time()
                    }
                }}
            )
            
            # Reactively update checklist checklist in MongoDB based on fact content
            val_lower = value.lower()
            if fact_type in ["blocker_candidate", "risk", "dependency"] and any(
                keyword in val_lower for keyword in ["security", "document", "soc2", "questionnaire", "legal", "procurement", "governance", "integration"]
            ):
                ticket = {
                    "id": f"tkt_ai_{int(time.time() * 1000)}",
                    "text": value,
                    "status": "open",
                    "source": "AI Agent (append_call_fact)",
                    "created_at": time.time()
                }
                deals_coll.update_one(
                    {"_id": deal_id},
                    {PUSH_OP: {"tickets": ticket}}
                )

            if "documents not prepared" in val_lower or "documents not sent" in val_lower or "questionnaire" in val_lower:
                deals_coll.update_one(
                    {"_id": deal_id, "checklist.id": "security_docs"},
                    {"$set": {"checklist.$.status": "delayed"}}
                )
                deals_coll.update_one(
                    {"_id": deal_id},
                    {PUSH_OP: {
                        "events": {
                            "type": "ticket_created",
                            "description": "Objection flagged: Prepare and deliver security architecture documents status set to delayed.",
                            "timestamp": time.time()
                        }
                    }}
                )
            elif "responsible" in val_lower or "sent" in val_lower or "completed" in val_lower:
                deals_coll.update_one(
                    {"_id": deal_id, "checklist.id": "security_docs"},
                    {"$set": {"checklist.$.status": "checked"}}
                )
                deals_coll.update_one(
                    {"_id": deal_id},
                    {PUSH_OP: {
                        "events": {
                            "type": "deal_updated",
                            "description": "Objection cleared: Security architecture documents status set to checked.",
                            "timestamp": time.time()
                        }
                    }}
                )
            logger.info(f"DB Fact appended for deal {deal_id}")
        except Exception as e:
            logging.exception(f"Database error in _db_append_fact: {e}")

    def _db_save_summary(self, deal_id: str, summary_data: dict):
        if not self.db_connected or self.db is None:
            return
        try:
            deals_coll = self.db['deals']
            summary_doc = {
                "primary_blocker": summary_data.get("primary_blocker"),
                "root_cause": summary_data.get("root_cause"),
                "evidence": summary_data.get("evidence", []),
                "recommended_next_points": summary_data.get("recommended_next_points", []),
                "confidence": float(summary_data.get("confidence", 1.0))
            }
            # Update summary and checklist item 'summary'
            deals_coll.update_one(
                {"_id": deal_id},
                {"$set": {
                    "summary": summary_doc,
                    "health_score": min(95, int((self._get_deal(deal_id) or {}).get("health_score", 55)) + 5),
                    "last_rep_update_days_ago": 0
                }}
            )
            deals_coll.update_one(
                {"_id": deal_id, "checklist.id": "summary"},
                {"$set": {"checklist.$.status": "checked"}}
            )
            
            # Log stage advanced and summary saved events in timeline
            deals_coll.update_one(
                {"_id": deal_id},
                {PUSH_OP: {
                    "events": {
                        "$each": [
                            {
                                "type": "stage_changed",
                                "description": "Stage advanced to 'Security Review' (via voice summary resolution)",
                                "timestamp": time.time()
                            },
                            {
                                "type": "summary_saved",
                                "description": f"AI saved final audit summary: {summary_data.get('primary_blocker')}",
                                "timestamp": time.time()
                            }
                        ]
                    }
                }}
            )
            
            # Also check if stakeholder meeting was confirmed based on evidence
            has_buyer = any("buyer" in e.lower() or "rohit" in e.lower() for e in summary_data.get("evidence", []))
            deals_coll.update_one(
                {"_id": deal_id, "checklist.id": "stakeholder"},
                {"$set": {"checklist.$.status": "checked" if has_buyer else "delayed"}}
            )
            deals_coll.update_one(
                {"_id": deal_id},
                {PUSH_OP: {
                    "events": {
                        "type": "deal_updated",
                        "description": f"Stakeholder meeting status updated to {'checked' if has_buyer else 'delayed'}",
                        "timestamp": time.time()
                    }
                }}
            )
            logger.info(f"DB Summary saved for deal {deal_id}")
        except Exception as e:
            logging.exception(f"Database error in _db_save_summary: {e}")

    async def _generate_and_speak_greeting(self, session: CallSession, assistant: AgentSession, lm: llm.LLM):
        """Generate a dynamic greeting and say it to the user."""
        logger.info(f"[{session.session_id}] Generating dynamic greeting...")
        try:
            greeting_ctx = llm.ChatContext()
            greeting_ctx.add_message(
                role="system",
                content=self._build_system_prompt(session),
            )
            greeting_ctx.add_message(
                role="user",
                content="Please generate the initial greeting for this call according to the policy. Speak directly to the rep. Do not include any other text.",
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
            
            # Broadcast greeting transcript to frontend
            if session.room:
                payload = json.dumps({
                    "type": "TRANSCRIPT",
                    "role": "assistant",
                    "text": greeting_text
                })
                await session.room.local_participant.publish_data(payload)
            
            # Database persistence for greeting transcript
            if self.db_connected and self.db is not None:
                try:
                    self.db['deals'].update_one(
                        {"_id": session.deal_id},
                        {PUSH_OP: {
                            "transcript": {
                                "speaker": "assistant",
                                "text": greeting_text,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        }}
                    )
                except Exception as e:
                    logging.exception(f"Failed to persist transcript to db: {e}")

            await assistant.say(greeting_text, allow_interruptions=True)
            logger.info(f"[{session.session_id}] Dynamic Greeting: {greeting_text}")
            
        except Exception as e:
            logger.exception(f"[{session.session_id}] Failed to generate dynamic greeting: {e}")
            fallback_greeting = "Hi there, I'm an AI assistant calling for a brief pipeline check. Does now work?"
            
            # Broadcast fallback greeting transcript to frontend
            if session.room:
                try:
                    payload = json.dumps({
                        "type": "TRANSCRIPT",
                        "role": "assistant",
                        "text": fallback_greeting
                    })
                    await session.room.local_participant.publish_data(payload)
                except Exception:
                    pass

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
            room=ctx.room,
        )
        self._active_sessions[session.session_id] = session

        self.agent_logger.log_call_start(session)
        logger.info(f"[{session.session_id}] Pipeline Review Call started | Rep={session.rep_id} | Deal={session.deal_id}")

        # Log call start in MongoDB
        if self.db_connected and self.db is not None:
            try:
                self.db['deals'].update_one(
                    {"_id": session.deal_id},
                    {PUSH_OP: {
                        "events": {
                            "type": "call_started",
                            "description": f"Voice AI audit session initiated (Session: {session.session_id})",
                            "timestamp": time.time()
                        }
                    }}
                )
            except Exception as e:
                logging.exception(f"Database error logging call start: {e}")

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        stt = deepgram.STT(
            model="nova-2-phonecall",
            language="en-US",
            smart_format=True,
            punctuate=True,
            interim_results=True,
        )

        fnc_ctx = PipelineReviewTools(id="pipeline_review_tools")

        initial_ctx = llm.ChatContext()
        initial_ctx.add_message(
            role="system",
            content=self._build_system_prompt(session),
        )
        lm = google.LLM(
            model=self.config.get("llm_model", "gemini-3.5-flash"),
            temperature=0.3,
            api_key=self.config.get("google_api_key"),
        )

        tts = deepgram.TTS()

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
            disconnected = asyncio.Event()

            @ctx.room.on("disconnected")
            def on_disconnected():
                disconnected.set()

            await disconnected.wait()
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
        eval_result = {}
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

        # Save finished call audit session detail to MongoDB
        if self.db_connected and self.db is not None:
            try:
                deals_coll = self.db['deals']
                call_doc = {
                    "session_id": session.session_id,
                    "call_sid": session.call_sid,
                    "phone_number": session.phone_number,
                    "started_at": session.started_at.isoformat(),
                    "ended_at": session.ended_at.isoformat() if session.ended_at else datetime.now(timezone.utc).isoformat(),
                    "duration_seconds": session.duration_seconds,
                    "turn_count": session.turn_count,
                    "total_tokens": session.total_tokens,
                    "transcript": session.transcript,
                    "tools_called": session.tools_called,
                    "actions_taken": session.actions_taken,
                    "cost_summary": cost_summary or {},
                    "evaluation": eval_result,
                    "timestamp": time.time()
                }
                deals_coll.update_one(
                    {"_id": session.deal_id},
                    {
                        PUSH_OP: {
                            "calls": call_doc,
                            "events": {
                                "type": "call_ended",
                                "description": f"Voice AI audit completed. Duration: {session.duration_seconds:.0f}s. Quality score: {eval_result.get('quality_score', 0.0):.1f}/10. Sentiment: {eval_result.get('sentiment', 'N/A')}",
                                "timestamp": time.time()
                            }
                        }
                    }
                )
                logger.info(f"DB Call details and audit event successfully saved for deal {session.deal_id}")
            except Exception as e:
                logging.exception(f"Database error in _finalize_session: {e}")

        self._active_sessions.pop(session.session_id, None)


async def _global_entrypoint(ctx: JobContext):
    """Pickleable entrypoint wrapper that lazily constructs the agent."""
    from config.settings import load_config
    config = load_config()
    agent_config = {
        "llm_model": config.llm_model,
        "tts_voice": config.tts_voice,
        "greeting": config.greeting,
        "google_api_key": config.google_api_key,
    }
    agent = VoiceAIAgent(agent_config)
    await agent.entrypoint(ctx)


def create_agent_worker() -> WorkerOptions:
    return WorkerOptions(
        entrypoint_fnc=_global_entrypoint,
        worker_type=WorkerType.ROOM,
        max_retry=3,
    )
