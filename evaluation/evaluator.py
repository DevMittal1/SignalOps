"""
Conversation Quality Evaluator
Uses LLM-as-judge to score call quality on multiple dimensions:
  - Task completion
  - Response relevance & accuracy
  - Conversational tone
  - Sentiment analysis
  - Hallucination detection signals
  - Issue flagging
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    session_id: str
    evaluated_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).replace(tzinfo=None).isoformat())

    # Scores (0.0–1.0)
    quality_score: float = 0.0
    task_completion: float = 0.0
    response_relevance: float = 0.0
    tone_score: float = 0.0
    conciseness_score: float = 0.0

    # Classification
    sentiment: str = "neutral"              # positive | neutral | negative
    resolution: str = "unknown"             # resolved | unresolved | escalated | unknown
    intent_category: str = "unknown"

    # Issues
    issues: list = field(default_factory=list)
    hallucination_risk: str = "low"         # low | medium | high
    needs_review: bool = False

    # Raw
    evaluator_reasoning: str = ""
    transcript_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "evaluated_at": self.evaluated_at,
            "quality_score": round(self.quality_score, 3),
            "task_completion": round(self.task_completion, 3),
            "response_relevance": round(self.response_relevance, 3),
            "tone_score": round(self.tone_score, 3),
            "conciseness_score": round(self.conciseness_score, 3),
            "sentiment": self.sentiment,
            "resolution": self.resolution,
            "intent_category": self.intent_category,
            "issues": self.issues,
            "hallucination_risk": self.hallucination_risk,
            "needs_review": self.needs_review,
            "evaluator_reasoning": self.evaluator_reasoning,
            "transcript_summary": self.transcript_summary,
        }


EVALUATION_PROMPT = """\
You are an expert quality assurance evaluator for AI voice assistants.
Evaluate the following conversation transcript and return ONLY valid JSON.

## Conversation Transcript
{transcript}

## Evaluation Criteria

Score each dimension 0.0–1.0 (1.0 = excellent):

1. **quality_score**: Overall conversation quality (weighted average)
2. **task_completion**: Did the assistant help the user accomplish their goal?
3. **response_relevance**: Were responses relevant, accurate, and helpful?
4. **tone_score**: Was the tone warm, professional, and natural for voice?
5. **conciseness_score**: Were responses appropriately concise for voice (not too long/short)?

Classify:
- **sentiment**: Overall user sentiment ("positive", "neutral", or "negative")
- **resolution**: Was the user's issue resolved? ("resolved", "unresolved", "escalated", "unknown")
- **intent_category**: What was the user's main intent? (e.g. "support", "information", "booking", "complaint", "other")
- **hallucination_risk**: Risk of factually incorrect statements ("low", "medium", "high")

Flag issues (list strings):
- "off_topic_response" — agent responded to something unrelated to user query
- "excessive_length" — agent responses were too long for voice
- "interrupted_mid_response" — agent was frequently interrupted (sign of poor pacing)
- "unclear_resolution" — it's not clear if the user got what they needed
- "inappropriate_tone" — tone was too formal, robotic, or unprofessional
- "potential_misinformation" — agent may have stated incorrect facts

Provide:
- **needs_review**: true if quality_score < 0.6 or hallucination_risk == "high" or issues count >= 2
- **evaluator_reasoning**: 1–2 sentences explaining the score
- **transcript_summary**: 1 sentence summary of what the call was about

Respond with ONLY this JSON structure:
{{
  "quality_score": 0.0,
  "task_completion": 0.0,
  "response_relevance": 0.0,
  "tone_score": 0.0,
  "conciseness_score": 0.0,
  "sentiment": "neutral",
  "resolution": "unknown",
  "intent_category": "unknown",
  "hallucination_risk": "low",
  "issues": [],
  "needs_review": false,
  "evaluator_reasoning": "",
  "transcript_summary": ""
}}
"""


class ConversationEvaluator:
    """
    Evaluates conversation quality using gemini-3.5-flash as an LLM judge.
    Designed to run asynchronously after a call ends — never on the critical path.
    """

    def __init__(
        self,
        model: str = "gemini-3.5-flash",
        max_transcript_chars: int = 8000,
        timeout_seconds: float = 30.0,
    ):
        self.model = model
        self.max_transcript_chars = max_transcript_chars
        self.timeout_seconds = timeout_seconds
        self.api_key = (
            os.environ.get("GEMINI_API_KEY") 
            or os.environ.get("GOOGLE_API_KEY") 
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self._http = httpx.AsyncClient(timeout=self.timeout_seconds)

    def _format_transcript(self, session: Any) -> str:
        lines = []
        for turn in session.transcript:
            role = turn.get("role", "unknown").upper()
            text = turn.get("text", "")
            lines.append(f"{role}: {text}")
        transcript = "\n".join(lines)
        # Truncate if too long
        if len(transcript) > self.max_transcript_chars:
            transcript = transcript[: self.max_transcript_chars] + "\n... [transcript truncated]"
        return transcript

    def _parse_json_robustly(self, raw: str) -> dict:
        raw = raw.strip()
        # Remove markdown wrapper
        if raw.startswith("```"):
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1:
                raw = raw[start:end+1]
        
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to fix missing commas between key-value pairs
            lines = raw.splitlines()
            rebuilt = []
            for i, line in enumerate(lines):
                trimmed = line.strip()
                if (
                    trimmed
                    and ":" in trimmed
                    and not trimmed.endswith(",")
                    and not trimmed.endswith("{")
                    and not trimmed.endswith("[")
                ):
                    # Check if next non-empty line starts with a double quote (key) or close brace
                    has_next_key = False
                    for next_line in lines[i+1:]:
                        next_trimmed = next_line.strip()
                        if next_trimmed:
                            if next_trimmed.startswith('"') or next_trimmed.startswith('}'):
                                has_next_key = next_trimmed.startswith('"')
                            break
                    if has_next_key:
                        line = line + ","
                rebuilt.append(line)
            
            repaired_raw = "\n".join(rebuilt)
            return json.loads(repaired_raw)

    async def evaluate_async(self, session: Any) -> dict:
        """Evaluate a completed call session. Returns evaluation dict."""
        if not self.api_key:
            logger.warning("No GEMINI_API_KEY or OPENAI_API_KEY set — skipping evaluation")
            return EvaluationResult(session_id=session.session_id).to_dict()

        transcript = self._format_transcript(session)
        if not transcript.strip():
            return EvaluationResult(session_id=session.session_id).to_dict()

        prompt = EVALUATION_PROMPT.format(transcript=transcript)

        # Route requests to Gemini's OpenAI-compatible endpoint, falling back to OpenAI if key starts with sk-
        url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        model = self.model
        if self.api_key.startswith("sk-"):
            url = "https://api.openai.com/v1/chat/completions"
            if model == "gemini-3.5-flash":
                model = "gpt-4o-mini"

        raw = ""
        try:
            resp = await self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 600,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            eval_data = self._parse_json_robustly(raw)

            result = EvaluationResult(
                session_id=session.session_id,
                quality_score=float(eval_data.get("quality_score", 0.5)),
                task_completion=float(eval_data.get("task_completion", 0.5)),
                response_relevance=float(eval_data.get("response_relevance", 0.5)),
                tone_score=float(eval_data.get("tone_score", 0.5)),
                conciseness_score=float(eval_data.get("conciseness_score", 0.5)),
                sentiment=eval_data.get("sentiment", "neutral"),
                resolution=eval_data.get("resolution", "unknown"),
                intent_category=eval_data.get("intent_category", "unknown"),
                hallucination_risk=eval_data.get("hallucination_risk", "low"),
                issues=eval_data.get("issues", []),
                needs_review=bool(eval_data.get("needs_review", False)),
                evaluator_reasoning=eval_data.get("evaluator_reasoning", ""),
                transcript_summary=eval_data.get("transcript_summary", ""),
            )
            return result.to_dict()

        except httpx.HTTPStatusError as e:
            logger.error(f"OpenAI API error during evaluation: {e.response.status_code}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse evaluation JSON: {e}. Raw response: {raw}")
        except Exception as e:
            logger.error(f"Evaluation failed: {e}", exc_info=True)

        return EvaluationResult(session_id=session.session_id).to_dict()

    async def batch_evaluate(self, sessions: list, concurrency: int = 5) -> list[dict]:
        """Evaluate multiple sessions with concurrency limit."""
        semaphore = asyncio.Semaphore(concurrency)

        async def eval_one(session):
            async with semaphore:
                return await self.evaluate_async(session)

        return await asyncio.gather(*[eval_one(s) for s in sessions])

    async def close(self):
        await self._http.aclose()


class EvaluationMetrics:
    """
    Aggregate evaluation metrics for reporting and alerting.
    """

    def __init__(self, evaluations: list[dict]):
        self.evaluations = evaluations

    def summary(self) -> dict:
        if not self.evaluations:
            return {}

        scores = [e["quality_score"] for e in self.evaluations if "quality_score" in e]
        sentiments = [e.get("sentiment", "neutral") for e in self.evaluations]
        resolutions = [e.get("resolution", "unknown") for e in self.evaluations]
        needs_review = sum(1 for e in self.evaluations if e.get("needs_review"))

        all_issues = []
        for e in self.evaluations:
            all_issues.extend(e.get("issues", []))

        issue_counts: dict[str, int] = {}
        for issue in all_issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

        n = len(self.evaluations)
        return {
            "total_evaluations": n,
            "avg_quality_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "min_quality_score": min(scores) if scores else 0,
            "max_quality_score": max(scores) if scores else 0,
            "needs_review_count": needs_review,
            "needs_review_pct": round(needs_review / n * 100, 1),
            "sentiment_distribution": {
                "positive": sentiments.count("positive"),
                "neutral": sentiments.count("neutral"),
                "negative": sentiments.count("negative"),
            },
            "resolution_distribution": {
                "resolved": resolutions.count("resolved"),
                "unresolved": resolutions.count("unresolved"),
                "escalated": resolutions.count("escalated"),
                "unknown": resolutions.count("unknown"),
            },
            "top_issues": sorted(issue_counts.items(), key=lambda x: -x[1])[:5],
        }
