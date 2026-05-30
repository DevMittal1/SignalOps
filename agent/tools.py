from typing import Annotated
from livekit.agents import llm
import logging

logger = logging.getLogger(__name__)

class PipelineReviewTools(llm.FunctionContext):
    """
    Tools for the Pipeline Review Agent.
    Note: These are mocked for demonstration purposes.
    """

    @llm.ai_callable(description="Get the purpose and context for calling a specific sales rep.")
    def get_call_context(
        self,
        rep_id: Annotated[str, llm.TypeInfo(description="The unique ID of the sales representative.")]
    ) -> dict:
        logger.info(f"Tool call: get_call_context(rep_id={rep_id})")
        return {
            "purpose": "Pipeline Visibility",
            "estimated_duration_minutes": 5,
            "manager_requested": False,
            "quarter_end_mode": True,
            "active_deals_to_review": 1
        }

    @llm.ai_callable(description="Retrieve official policy answers about call recording, privacy, and data usage.")
    def get_agent_policy(
        self,
        topic: Annotated[str, llm.TypeInfo(description="The topic to look up (e.g., 'recording', 'privacy', 'quota').")]
    ) -> dict:
        logger.info(f"Tool call: get_agent_policy(topic={topic})")
        policies = {
            "recording": "The call may be recorded for internal revenue visibility. Collected information is used to improve deal clarity and may be reviewed by managers and RevOps according to company policy.",
            "visibility": "Information collected is shared with your manager and the RevOps team to identify and resolve deal bottlenecks.",
            "quota": "This call is for operational visibility and does not directly change your quota or attainment metrics.",
            "purpose": "The purpose of this call is to identify specific blockers in your pipeline to help the team resolve them effectively."
        }
        return {"answer": policies.get(topic, "I don't have a specific policy on that topic, but I can tell you this is a standard pipeline visibility check.")}

    @llm.ai_callable(description="Fetch the core details of a specific deal from the CRM.")
    def get_deal_context(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal/opportunity.")]
    ) -> dict:
        logger.info(f"Tool call: get_deal_context(deal_id={deal_id})")
        return {
            "account_name": "Acme Cloud",
            "opportunity_name": "Acme Renewal Expansion",
            "amount": 180000,
            "stage": "Proposal",
            "days_in_stage": 29,
            "close_date": "2026-06-18",
            "close_date_changes_90d": 4,
            "last_rep_update_days_ago": 6
        }

    @llm.ai_callable(description="Fetch the history of stage changes and close-date movements for a deal.")
    def get_deal_timeline(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_deal_timeline(deal_id={deal_id})")
        return {
            "events": [
                {"type": "stage_change", "from": "Discovery", "to": "Demo", "date": "2026-04-02"},
                {"type": "stage_change", "from": "Demo", "to": "Proposal", "date": "2026-05-01"},
                {"type": "close_date_change", "from": "2026-05-30", "to": "2026-06-12", "date": "2026-05-14"},
                {"type": "close_date_change", "from": "2026-06-12", "to": "2026-06-18", "date": "2026-05-24"}
            ]
        }

    @llm.ai_callable(description="Retrieve historical profile and performance patterns for a sales rep.")
    def get_rep_context(
        self,
        rep_id: Annotated[str, llm.TypeInfo(description="The unique ID of the sales representative.")]
    ) -> dict:
        logger.info(f"Tool call: get_rep_context(rep_id={rep_id})")
        return {
            "name": "Aarav",
            "team": "Enterprise East",
            "quota": 1200000,
            "forecast_accuracy_90d": 0.57,
            "avg_close_slip_days": 14,
            "notes": ["Strong at discovery", "Often optimistic in late-stage deals"]
        }

    @llm.ai_callable(description="Retrieve summary and objections from the last customer interaction.")
    def get_last_customer_interaction(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_last_customer_interaction(deal_id={deal_id})")
        return {
            "last_meeting_date": "2026-05-20",
            "summary": "Customer asked for security architecture docs and timeline for SOC2 evidence.",
            "objections": ["Need security sign-off", "Want implementation plan before legal review"],
            "next_step": "send docs"
        }

    @llm.ai_callable(description="Retrieve the stakeholder map for a deal, including champion and blockers.")
    def get_stakeholder_map(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_stakeholder_map(deal_id={deal_id})")
        return {
            "champion": {"name": "Nina", "title": "Director of Ops", "influence": "high"},
            "economic_buyer": {"name": "Rohit", "title": "VP Finance", "influence": "high"},
            "security": {"name": "Jordan", "title": "IT Manager", "influence": "medium"},
            "legal": None,
            "risk_flags": ["No confirmed economic buyer meeting", "Legal stakeholder not named"]
        }

    @llm.ai_callable(description="Get activity health metrics (emails, meetings, outreach) for a deal.")
    def get_activity_health(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_activity_health(deal_id={deal_id})")
        return {
            "days_since_customer_email": 4,
            "days_since_customer_meeting": 11,
            "days_since_rep_outreach": 2,
            "open_tasks": 3,
            "open_tasks_overdue": 1,
            "last_customer_reply_sentiment": "neutral"
        }

    @llm.ai_callable(description="Inspect internal dependencies that may be blocking a deal.")
    def get_internal_dependency_status(
        self,
        deal_id: Annotated[str, llm.TypeInfo(description="The unique ID of the deal.")]
    ) -> dict:
        logger.info(f"Tool call: get_internal_dependency_status(deal_id={deal_id})")
        return {
            "dependencies": [
                {"type": "security_docs", "owner_team": "Solutions Engineering", "status": "open", "age_days": 9},
                {"type": "pricing_exception", "owner_team": "Sales Manager", "status": "approved"}
            ]
        }

    @llm.ai_callable(description="Define a business or pipeline-specific term for the rep.")
    def explain_term(
        self,
        term: Annotated[str, llm.TypeInfo(description="The term to define.")]
    ) -> dict:
        logger.info(f"Tool call: explain_term(term={term})")
        definitions = {
            "dependency": "A dependency is any action, approval, document, or stakeholder input that must happen before the deal can continue.",
            "blocker": "A blocker is a specific obstacle preventing a deal from moving to the next stage.",
            "economic buyer": "The person with the ultimate authority to approve the spend for a deal."
        }
        return {"definition": definitions.get(term.lower(), "I don't have a specific definition for that term in my policy.")}

    @llm.ai_callable(description="Retrieve a static list of sharp management-style follow-up questions to use when a rep gives a vague answer.")
    def get_static_followup(
        self,
        statement: Annotated[str, llm.TypeInfo(description="The vague statement made by the rep.")]
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

    @llm.ai_callable(description="Store a verified fact discovered during the call conversation.")
    def append_call_fact(
        self,
        call_id: Annotated[str, llm.TypeInfo(description="The unique ID of the current call session.")],
        fact_type: Annotated[str, llm.TypeInfo(description="The type of fact (e.g., 'blocker_candidate', 'owner').")],
        value: Annotated[str, llm.TypeInfo(description="The content of the fact.")],
        confidence: Annotated[float, llm.TypeInfo(description="Confidence score (0.0 to 1.0).")]
    ) -> dict:
        logger.info(f"Fact recorded: {fact_type}={value} (conf={confidence})")
        return {"success": True}

    @llm.ai_callable(description="Persist the final structured summary and evidence at the end of the call.")
    def save_call_summary(
        self,
        call_id: Annotated[str, llm.TypeInfo(description="The unique ID of the call session.")],
        deal_id: Annotated[str, llm.TypeInfo(description="The deal ID.")],
        primary_blocker: Annotated[str, llm.TypeInfo(description="The main identified blocker.")],
        root_cause: Annotated[str, llm.TypeInfo(description="The root cause of the blocker.")],
        evidence: Annotated[list[str], llm.TypeInfo(description="Key pieces of evidence supporting the findings.")],
        confidence: Annotated[float, llm.TypeInfo(description="Final confidence score.")]
    ) -> dict:
        logger.info(f"Summary saved for call {call_id}: {primary_blocker}")
        return {"success": True, "summary_id": "sum_5521"}
