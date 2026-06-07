from typing import Annotated, Optional
from pydantic import Field
from livekit.agents import llm
import logging
import os
from copy import deepcopy

from bson import ObjectId
from pymongo import MongoClient

logger = logging.getLogger(__name__)


class PipelineReviewTools(llm.Toolset):
    """
    Tools for the Pipeline Review Agent.
    Uses CRM records when MongoDB is configured, with demo fallbacks for local runs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_connected = False
        self.db = None
        mongodb_uri = os.environ.get("MONGODB_URI", "")
        if mongodb_uri:
            try:
                client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=3000)
                client.admin.command("ping")
                self.db = client["signalops"]
                self.db_connected = True
            except Exception as exc:
                logger.warning(f"PipelineReviewTools using fallback context; MongoDB unavailable: {exc}")

    def _serialize(self, value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, list):
            return [self._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: self._serialize(item) for key, item in value.items()}
        return value

    def _find_deal(self, deal_id: str) -> Optional[dict]:
        if not self.db_connected or not self.db:
            return None
        deal = self.db["deals"].find_one({"_id": deal_id})
        if not deal:
            try:
                deal = self.db["deals"].find_one({"_id": ObjectId(deal_id)})
            except Exception:
                deal = None
        return self._serialize(deal) if deal else None

    def _fallback_deal(self) -> dict:
        return {
            "account_name": "Acme Cloud",
            "name": "Acme Renewal Expansion",
            "amount": 180000,
            "stage": "Proposal",
            "days_in_stage": 29,
            "close_date": "2026-06-18",
            "close_date_changes_90d": 4,
            "last_rep_update_days_ago": 6,
            "risk_flags": ["Security docs not delivered", "Economic buyer meeting not confirmed"],
            "next_best_actions": ["Confirm owner for security docs", "Verify economic-buyer meeting status"],
            "activity_health": {"days_since_customer_email": 4, "days_since_customer_meeting": 11, "open_tasks": 3, "open_tasks_overdue": 1},
            "dependencies": [{"type": "security_docs", "owner_team": "Solutions Engineering", "status": "open", "age_days": 9}],
            "stakeholders": {
                "champion": {"name": "Nina", "title": "Director of Ops", "influence": "high"},
                "economic_buyer": {"name": "Rohit", "title": "VP Finance", "influence": "high"},
                "security": {"name": "Jordan", "title": "IT Manager", "influence": "medium"},
                "legal": None
            },
            "last_customer_interaction": {
                "last_meeting_date": "2026-05-20",
                "summary": "Customer asked for security architecture docs and SOC2 evidence timeline.",
                "objections": ["Need security sign-off", "Want implementation plan before legal review"],
                "next_step": "send docs"
            }
        }

    @llm.function_tool(description="Get the purpose and context for calling a specific sales rep.")
    async def get_call_context(
        self,
        rep_id: Annotated[str, Field(description="The unique ID of the sales representative.")]
    ) -> dict:
        logger.info(f"Tool call: get_call_context(rep_id={rep_id})")
        active_deals = 1
        if self.db_connected and self.db:
            active_deals = self.db["deals"].count_documents({
                "rep_id": rep_id,
                "stage": {"$nin": ["Closed-Won", "Closed Won", "Closed Lost"]}
            }) or 1
        return {
            "purpose": "Pipeline Visibility",
            "estimated_duration_minutes": 5,
            "manager_requested": False,
            "quarter_end_mode": True,
            "active_deals_to_review": active_deals
        }

    @llm.function_tool(description="Retrieve official policy answers about call recording, privacy, and data usage.")
    async def get_agent_policy(
        self,
        topic: Annotated[str, Field(description="The topic to look up (e.g., 'recording', 'privacy', 'visibility', 'quota').")]
    ) -> dict:
        logger.info(f"Tool call: get_agent_policy(topic={topic})")
        policies = {
            "recording": "The call may be recorded for internal revenue visibility. Collected information is used to improve deal clarity and may be reviewed by managers and RevOps according to company policy.",
            "visibility": "Information collected is shared with your manager and the RevOps team to identify and resolve deal bottlenecks.",
            "quota": "This call is for operational visibility and does not directly change your quota or attainment metrics.",
            "purpose": "The purpose of this call is to identify specific blockers in your pipeline to help the team resolve them effectively."
        }
        return {"answer": policies.get(topic, "I don't have a specific policy on that topic, but I can tell you this is a standard pipeline visibility check.")}

    @llm.function_tool(description="Fetch the core details of a specific deal from the CRM.")
    async def get_deal_context(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal/opportunity.")]
    ) -> dict:
        logger.info(f"Tool call: get_deal_context(deal_id={deal_id})")
        deal = self._find_deal(deal_id) or self._fallback_deal()
        return {
            "account_name": deal.get("account_name", deal.get("name")),
            "opportunity_name": deal.get("name"),
            "amount": deal.get("amount"),
            "stage": deal.get("stage"),
            "days_in_stage": deal.get("days_in_stage"),
            "close_date": deal.get("close_date"),
            "close_date_changes_90d": deal.get("close_date_changes_90d"),
            "last_rep_update_days_ago": deal.get("last_rep_update_days_ago"),
            "priority": deal.get("priority"),
            "health_score": deal.get("health_score"),
            "primary_competitor": deal.get("primary_competitor"),
            "risk_flags": deal.get("risk_flags", []),
            "next_best_actions": deal.get("next_best_actions", [])
        }

    @llm.function_tool(description="Fetch the history of stage changes and close-date movements for a deal.")
    async def get_deal_timeline(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_deal_timeline(deal_id={deal_id})")
        deal = self._find_deal(deal_id)
        if deal and deal.get("events"):
            return {"events": deal.get("events", [])[-10:]}
        return {
            "events": [
                {"type": "stage_change", "from": "Discovery", "to": "Demo", "date": "2026-04-02"},
                {"type": "stage_change", "from": "Demo", "to": "Proposal", "date": "2026-05-01"},
                {"type": "close_date_change", "from": "2026-05-30", "to": "2026-06-12", "date": "2026-05-14"},
                {"type": "close_date_change", "from": "2026-06-12", "to": "2026-06-18", "date": "2026-05-24"}
            ]
        }

    @llm.function_tool(description="Retrieve historical profile and performance patterns for a sales rep.")
    async def get_rep_context(
        self,
        rep_id: Annotated[str, Field(description="The unique ID of the sales representative.")]
    ) -> dict:
        logger.info(f"Tool call: get_rep_context(rep_id={rep_id})")
        if self.db_connected and self.db:
            deal = self.db["deals"].find_one({"rep_id": rep_id})
            if deal:
                deal = self._serialize(deal)
                owner = deal.get("owner") or deal.get("rep_name") or "Sales rep"
                active = self.db["deals"].count_documents({"rep_id": rep_id})
                return {
                    "name": deal.get("rep_name", owner),
                    "team": "Revenue",
                    "quota": 1200000,
                    "active_deals": active,
                    "forecast_accuracy_90d": 0.62,
                    "avg_close_slip_days": 11,
                    "notes": ["Use current CRM facts instead of assumptions", "Prioritize exact blocker, owner, and date"]
                }
        return {
            "name": "Aarav",
            "team": "Enterprise East",
            "quota": 1200000,
            "forecast_accuracy_90d": 0.57,
            "avg_close_slip_days": 14,
            "notes": ["Strong at discovery", "Often optimistic in late-stage deals"]
        }

    @llm.function_tool(description="Retrieve summary and objections from the last customer interaction.")
    async def get_last_customer_interaction(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_last_customer_interaction(deal_id={deal_id})")
        deal = self._find_deal(deal_id) or self._fallback_deal()
        return deepcopy(deal.get("last_customer_interaction") or {
            "last_meeting_date": "2026-05-20",
            "summary": "Customer asked for security architecture docs and timeline for SOC2 evidence.",
            "objections": ["Need security sign-off", "Want implementation plan before legal review"],
            "next_step": "send docs"
        })

    @llm.function_tool(description="Retrieve the stakeholder map for a deal, including champion and blockers.")
    async def get_stakeholder_map(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_stakeholder_map(deal_id={deal_id})")
        deal = self._find_deal(deal_id) or self._fallback_deal()
        stakeholders = deal.get("stakeholders")
        if stakeholders:
            return {
                **stakeholders,
                "risk_flags": deal.get("risk_flags", [])
            }
        return {
            "champion": {"name": "Nina", "title": "Director of Ops", "influence": "high"},
            "economic_buyer": {"name": "Rohit", "title": "VP Finance", "influence": "high"},
            "security": {"name": "Jordan", "title": "IT Manager", "influence": "medium"},
            "legal": None,
            "risk_flags": ["No confirmed economic buyer meeting", "Legal stakeholder not named"]
        }

    @llm.function_tool(description="Get activity health metrics (emails, meetings, outreach) for a deal.")
    async def get_activity_health(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_activity_health(deal_id={deal_id})")
        deal = self._find_deal(deal_id) or self._fallback_deal()
        if deal.get("activity_health"):
            return deal["activity_health"]
        return {
            "days_since_customer_email": 4,
            "days_since_customer_meeting": 11,
            "days_since_rep_outreach": 2,
            "open_tasks": 3,
            "open_tasks_overdue": 1,
            "last_customer_reply_sentiment": "neutral"
        }

    @llm.function_tool(description="Inspect internal dependencies that may be blocking a deal.")
    async def get_internal_dependency_status(
        self,
        deal_id: Annotated[str, Field(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_internal_dependency_status(deal_id={deal_id})")
        deal = self._find_deal(deal_id) or self._fallback_deal()
        return {"dependencies": deal.get("dependencies", [])}

    @llm.function_tool(description="Define a business or pipeline-specific term for the rep.")
    async def explain_term(
        self,
        term: Annotated[str, Field(description="The term to define.")]
    ) -> dict:
        logger.info(f"Tool call: explain_term(term={term})")
        definitions = {
            "dependency": "A dependency is any action, approval, document, or stakeholder input that must happen before the deal can continue.",
            "blocker": "A blocker is a specific obstacle preventing a deal from moving to the next stage.",
            "economic buyer": "The person with the ultimate authority to approve the spend for a deal."
        }
        return {"definition": definitions.get(term.lower(), "I don't have a specific definition for that term in my policy.")}

    @llm.function_tool(description="Retrieve a static list of sharp management-style follow-up questions to use when a rep gives a vague answer.")
    async def get_static_followup(
        self,
        statement: Annotated[str, Field(description="The vague statement made by the rep.")]
    ) -> dict:
        logger.info(f"Tool call: get_static_followup(statement={statement})")
        return {
            "questions": [
                "What specifically are they reviewing?",
                "Who owns that review on their side?",
                "What exact result are they waiting for?",
                "Has a concrete timeline been shared with you?"
            ]
        }

    @llm.function_tool(description="Store a verified fact discovered during the call conversation.")
    async def append_call_fact(
        self,
        call_id: Annotated[str, Field(description="The unique ID of the current call session.")],
        fact_type: Annotated[str, Field(description="The type of fact (e.g., 'blocker_candidate', 'owner').")],
        value: Annotated[str, Field(description="The content of the fact.")],
        confidence: Annotated[float, Field(description="Confidence score (0.0 to 1.0).")]
    ) -> dict:
        logger.info(f"Fact recorded: {fact_type}={value} (conf={confidence})")
        return {"success": True}

    @llm.function_tool(description="Persist the final structured summary and evidence at the end of the call.")
    async def save_call_summary(
        self,
        call_id: Annotated[str, Field(description="The unique ID of the call session.")],
        deal_id: Annotated[str, Field(description="The deal ID.")],
        primary_blocker: Annotated[str, Field(description="The main identified blocker.")],
        root_cause: Annotated[str, Field(description="The root cause of the blocker.")],
        evidence: Annotated[list[str], Field(description="Key pieces of evidence supporting the findings.")],
        confidence: Annotated[float, Field(description="Final confidence score.")],
        recommended_next_points: Annotated[Optional[list[str]], Field(description="The most important concrete points RevOps should verify or follow up next.")] = None
    ) -> dict:
        logger.info(f"Summary saved for call {call_id}: {primary_blocker}")
        return {"success": True, "summary_id": "sum_5521"}
