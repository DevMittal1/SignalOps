import os
import sys
import time
import json
import logging
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import jwt
import bcrypt
from pymongo import MongoClient
from bson import ObjectId
from config.settings import load_config

# Set up simple logging for the server
logging.basicConfig(level=logging.INFO, format="[Server] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Constants
MONGODB_URI = os.environ.get("MONGODB_URI", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "signalops-super-jwt-secret-key-2026")

# Database connection state
db_connected = False
db = None
mock_users = {}
mock_deals = {}

# Connect to MongoDB
if MONGODB_URI:
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
        # Test connection
        client.admin.command('ping')
        db = client['signalops']
        db_connected = True
        logger.info("Connected successfully to MongoDB Atlas")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB Atlas: {e}. Falling back to in-memory database.")
else:
    logger.warning("MONGODB_URI not set. Running with in-memory database.")

# Shared global state for inbound trigger
trigger_state = {
    "ringing": False,
    "room_name": "",
    "rep_id": "rep_204",
    "deal_id": "deal_8931"
}

# Seed Data
DEFAULT_DEALS = [
    {
        "_id": "deal_8931",
        "name": "Acme Renewal Expansion",
        "amount": 180000,
        "confidence": 75,
        "stage": "Proposal",
        "close_date": "2026-06-18",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "checked" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "pending" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
            { "id": "stakeholder", "text": "Confirm Rohit (Economic Buyer) meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 86400 }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time()
    },
    {
        "_id": "deal_4412",
        "name": "Globex Cloud Migration",
        "amount": 340000,
        "confidence": 85,
        "stage": "Security Review",
        "close_date": "2026-07-05",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "checked" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "checked" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
            { "id": "stakeholder", "text": "Confirm Rohit (Economic Buyer) meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [
            { "id": "tkt_01", "text": "Customer requested customized data residency policy doc", "status": "open", "source": "AI Agent (append_call_fact)", "created_at": time.time() - 3600 }
        ],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 172800 },
            { "type": "objection_flagged", "description": "Objection tickets generated: Custom data residency document request.", "timestamp": time.time() - 3600 }
        ],
        "facts": [
            { "type": "blocker_candidate", "value": "Customer requested custom data residency policy doc", "confidence": 1.0, "timestamp": time.time() }
        ],
        "summary": None,
        "created_at": time.time() - 3600
    },
    {
        "_id": "deal_7721",
        "name": "Initech Compliance Audit",
        "amount": 95000,
        "confidence": 50,
        "stage": "Discovery",
        "close_date": "2026-06-30",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "pending" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "pending" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
            { "id": "stakeholder", "text": "Confirm Rohit (Economic Buyer) meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 259200 }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time() - 7200
    }
]

EXTRA_DEFAULT_DEALS = [
    {
        "_id": "deal_1188",
        "name": "Northstar Health EHR Automation",
        "amount": 260000,
        "confidence": 62,
        "stage": "Procurement",
        "close_date": "2026-06-28",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "checked" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "checked" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "checked" },
            { "id": "stakeholder", "text": "Confirm economic buyer meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [
            { "id": "tkt_1188_01", "text": "Procurement needs vendor risk questionnaire before PO routing", "status": "open", "source": "RevOps Risk Scan", "created_at": time.time() - 5400 }
        ],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 345600 },
            { "type": "stage_changed", "description": "Stage updated from Security Review to Procurement", "timestamp": time.time() - 86400 },
            { "type": "ticket_created", "description": "Ticket created: vendor risk questionnaire required.", "timestamp": time.time() - 5400 }
        ],
        "facts": [
            { "type": "blocker_candidate", "value": "Procurement requires vendor risk questionnaire", "confidence": 0.9, "timestamp": time.time() - 5400 }
        ],
        "summary": None,
        "created_at": time.time() - 5400
    },
    {
        "_id": "deal_2267",
        "name": "Meridian Bank Fraud Ops",
        "amount": 410000,
        "confidence": 58,
        "stage": "Security Review",
        "close_date": "2026-07-12",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "checked" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "pending" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
            { "id": "stakeholder", "text": "Confirm economic buyer meeting status", "status": "checked" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 432000 },
            { "type": "close_date_changed", "description": "Close date updated from 2026-06-30 to 2026-07-12", "timestamp": time.time() - 172800 }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time() - 10800
    },
    {
        "_id": "deal_5094",
        "name": "BrightCart Support Deflection",
        "amount": 72000,
        "confidence": 44,
        "stage": "Discovery",
        "close_date": "2026-07-20",
        "rep_id": "rep_204",
        "rep_name": "Aarav",
        "checklist": [
            { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "pending" },
            { "id": "blocker", "text": "Primary deal blocker identified", "status": "pending" },
            { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
            { "id": "stakeholder", "text": "Confirm economic buyer meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [
            { "id": "tkt_5094_01", "text": "Champion requested proof that Zendesk integration supports custom fields", "status": "open", "source": "AE Note", "created_at": time.time() - 7200 }
        ],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 259200 },
            { "type": "ticket_created", "description": "Ticket created: Zendesk integration proof requested.", "timestamp": time.time() - 7200 }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time() - 14400
    }
]

DEFAULT_DEALS.extend(EXTRA_DEFAULT_DEALS)

REALISTIC_DEAL_DETAILS = {
    "deal_8931": {
        "account_name": "Acme Cloud",
        "industry": "B2B SaaS",
        "region": "North America",
        "priority": "high",
        "health_score": 68,
        "days_in_stage": 29,
        "close_date_changes_90d": 4,
        "primary_competitor": "Nimbus",
        "last_rep_update_days_ago": 6,
        "risk_flags": ["Security docs not delivered", "Economic buyer meeting not confirmed", "Close date slipped 4 times"],
        "next_best_actions": [
            "Confirm who owns the security architecture packet internally",
            "Record whether SOC2 evidence timeline has been sent",
            "Verify Rohit's economic-buyer meeting status"
        ],
        "stakeholders": {
            "champion": {"name": "Nina Patel", "title": "Director of Operations", "influence": "high", "sentiment": "supportive"},
            "economic_buyer": {"name": "Rohit Mehra", "title": "VP Finance", "influence": "high", "sentiment": "unconfirmed"},
            "security": {"name": "Jordan Lee", "title": "IT Manager", "influence": "medium", "sentiment": "waiting on evidence"},
            "legal": None
        },
        "activity_health": {"days_since_customer_email": 4, "days_since_customer_meeting": 11, "days_since_rep_outreach": 2, "open_tasks": 3, "open_tasks_overdue": 1},
        "dependencies": [
            {"type": "security_docs", "owner_team": "Solutions Engineering", "owner": "AE + SE", "status": "open", "age_days": 9},
            {"type": "economic_buyer_meeting", "owner_team": "Sales", "owner": "AE", "status": "open", "age_days": 6}
        ],
        "last_customer_interaction": {
            "last_meeting_date": "2026-05-20",
            "summary": "Customer asked for security architecture docs and timeline for SOC2 evidence.",
            "objections": ["Need security sign-off", "Want implementation plan before legal review"],
            "next_step": "Send security packet and SOC2 timeline"
        }
    },
    "deal_4412": {
        "account_name": "Globex",
        "industry": "Cloud Infrastructure",
        "region": "APAC",
        "priority": "critical",
        "health_score": 74,
        "days_in_stage": 18,
        "close_date_changes_90d": 2,
        "primary_competitor": "CloudPeak",
        "last_rep_update_days_ago": 2,
        "risk_flags": ["Custom data residency document needed", "Security team evaluating deployment architecture"],
        "next_best_actions": ["Identify owner for residency policy", "Confirm security review completion date", "Capture whether legal has received redlines"],
        "stakeholders": {
            "champion": {"name": "Meera Shah", "title": "VP Cloud Ops", "influence": "high", "sentiment": "supportive"},
            "economic_buyer": {"name": "Daniel Wu", "title": "CIO", "influence": "high", "sentiment": "engaged"},
            "security": {"name": "Priyanka Rao", "title": "Security Architect", "influence": "high", "sentiment": "needs residency doc"},
            "legal": {"name": "Alicia Gomez", "title": "Counsel", "influence": "medium", "sentiment": "not started"}
        },
        "activity_health": {"days_since_customer_email": 1, "days_since_customer_meeting": 5, "days_since_rep_outreach": 1, "open_tasks": 4, "open_tasks_overdue": 0},
        "dependencies": [{"type": "data_residency_policy", "owner_team": "Security", "owner": "Security + Legal", "status": "open", "age_days": 4}],
        "last_customer_interaction": {"last_meeting_date": "2026-06-02", "summary": "Security asked for custom data residency policy and deployment diagram.", "objections": ["Data residency proof"], "next_step": "Deliver policy draft"}
    },
    "deal_7721": {
        "account_name": "Initech",
        "industry": "Professional Services",
        "region": "North America",
        "priority": "medium",
        "health_score": 46,
        "days_in_stage": 36,
        "close_date_changes_90d": 3,
        "primary_competitor": "Manual process",
        "last_rep_update_days_ago": 12,
        "risk_flags": ["Discovery stalled", "No confirmed pain metric", "Champion influence unclear"],
        "next_best_actions": ["Clarify business impact of audit delay", "Identify economic buyer", "Confirm next meeting date"],
        "stakeholders": {
            "champion": {"name": "Peter Gibbons", "title": "Operations Manager", "influence": "medium", "sentiment": "curious"},
            "economic_buyer": None,
            "security": None,
            "legal": None
        },
        "activity_health": {"days_since_customer_email": 9, "days_since_customer_meeting": 21, "days_since_rep_outreach": 8, "open_tasks": 2, "open_tasks_overdue": 2},
        "dependencies": [{"type": "business_case", "owner_team": "Sales", "owner": "AE", "status": "open", "age_days": 14}],
        "last_customer_interaction": {"last_meeting_date": "2026-05-18", "summary": "Customer is interested but has not quantified compliance audit impact.", "objections": ["No urgent timeline"], "next_step": "Quantify audit savings"}
    },
    "deal_1188": {
        "account_name": "Northstar Health",
        "industry": "Healthcare",
        "region": "North America",
        "priority": "high",
        "health_score": 71,
        "days_in_stage": 12,
        "close_date_changes_90d": 1,
        "primary_competitor": "Legacy workflow",
        "last_rep_update_days_ago": 1,
        "risk_flags": ["Vendor risk questionnaire incomplete", "Procurement requires HIPAA attestation"],
        "next_best_actions": ["Confirm questionnaire owner", "Capture HIPAA attestation status", "Verify procurement PO routing date"],
        "stakeholders": {
            "champion": {"name": "Dr. Elena Morris", "title": "Chief Medical Informatics Officer", "influence": "high", "sentiment": "supportive"},
            "economic_buyer": {"name": "Karen Blake", "title": "CFO", "influence": "high", "sentiment": "approved budget"},
            "security": {"name": "Samir Khan", "title": "GRC Lead", "influence": "medium", "sentiment": "waiting on questionnaire"},
            "legal": {"name": "Monica Reed", "title": "Healthcare Counsel", "influence": "medium", "sentiment": "reviewing BAA"}
        },
        "activity_health": {"days_since_customer_email": 2, "days_since_customer_meeting": 6, "days_since_rep_outreach": 1, "open_tasks": 5, "open_tasks_overdue": 1},
        "dependencies": [{"type": "vendor_risk_questionnaire", "owner_team": "Security", "owner": "GRC", "status": "open", "age_days": 7}],
        "last_customer_interaction": {"last_meeting_date": "2026-06-01", "summary": "Procurement requested vendor risk questionnaire and HIPAA attestation.", "objections": ["Procurement packet incomplete"], "next_step": "Complete vendor packet"}
    },
    "deal_2267": {
        "account_name": "Meridian Bank",
        "industry": "Financial Services",
        "region": "EMEA",
        "priority": "critical",
        "health_score": 59,
        "days_in_stage": 24,
        "close_date_changes_90d": 3,
        "primary_competitor": "SentinelAI",
        "last_rep_update_days_ago": 5,
        "risk_flags": ["Model governance review unresolved", "Security review has no owner date", "Competitive bakeoff still open"],
        "next_best_actions": ["Identify model risk owner", "Confirm if InfoSec received architecture diagram", "Capture competitor decision criteria"],
        "stakeholders": {
            "champion": {"name": "Oliver Hart", "title": "Head of Fraud Ops", "influence": "high", "sentiment": "supportive"},
            "economic_buyer": {"name": "Amelia Cross", "title": "COO", "influence": "high", "sentiment": "engaged"},
            "security": {"name": "Nadia Stein", "title": "InfoSec Director", "influence": "high", "sentiment": "reviewing"},
            "legal": {"name": "Theo Laurent", "title": "Procurement Counsel", "influence": "medium", "sentiment": "waiting"}
        },
        "activity_health": {"days_since_customer_email": 3, "days_since_customer_meeting": 13, "days_since_rep_outreach": 3, "open_tasks": 6, "open_tasks_overdue": 2},
        "dependencies": [{"type": "model_governance", "owner_team": "Product Security", "owner": "AI Governance", "status": "open", "age_days": 11}],
        "last_customer_interaction": {"last_meeting_date": "2026-05-29", "summary": "Bank wants model governance evidence before selecting a vendor.", "objections": ["Model risk review", "Competitive bakeoff"], "next_step": "Provide governance packet"}
    },
    "deal_5094": {
        "account_name": "BrightCart",
        "industry": "E-commerce",
        "region": "North America",
        "priority": "medium",
        "health_score": 52,
        "days_in_stage": 15,
        "close_date_changes_90d": 0,
        "primary_competitor": "Zendesk native automation",
        "last_rep_update_days_ago": 4,
        "risk_flags": ["Technical fit proof needed", "No executive sponsor yet"],
        "next_best_actions": ["Confirm Zendesk custom-field integration", "Find executive sponsor", "Quantify ticket deflection target"],
        "stakeholders": {
            "champion": {"name": "Lena Brooks", "title": "Support Ops Lead", "influence": "medium", "sentiment": "interested"},
            "economic_buyer": None,
            "security": {"name": "Miguel Torres", "title": "IT Admin", "influence": "low", "sentiment": "neutral"},
            "legal": None
        },
        "activity_health": {"days_since_customer_email": 5, "days_since_customer_meeting": 8, "days_since_rep_outreach": 4, "open_tasks": 3, "open_tasks_overdue": 1},
        "dependencies": [{"type": "integration_validation", "owner_team": "Solutions Engineering", "owner": "SE", "status": "open", "age_days": 5}],
        "last_customer_interaction": {"last_meeting_date": "2026-06-03", "summary": "Champion asked whether Zendesk custom fields sync bidirectionally.", "objections": ["Integration proof"], "next_step": "Show integration proof"}
    }
}

for deal in DEFAULT_DEALS:
    deal.update(REALISTIC_DEAL_DETAILS.get(deal["_id"], {}))


def seed_database():
    if db_connected:
        try:
            deals_coll = db['deals']
            for deal in DEFAULT_DEALS:
                deals_coll.replace_one({"_id": deal["_id"]}, deal, upsert=True)
            logger.info("Database seeded successfully with default deals.")
        except Exception as e:
            logger.error(f"Error seeding database: {e}")
    else:
        for deal in DEFAULT_DEALS:
            mock_deals[deal["_id"]] = dict(deal)
        logger.info("In-memory database initialized with default deals.")


def safe_account_id(username: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", username.strip().lower())
    return safe.strip("_") or "user"


def build_default_deals_for_user(username: str):
    owner_key = safe_account_id(username)
    now = time.time()
    user_deals = []
    for index, template in enumerate(DEFAULT_DEALS):
        deal = json.loads(json.dumps(template))
        original_id = deal["_id"]
        deal["_id"] = f"{owner_key}_{original_id}"
        deal["owner"] = username
        deal["rep_id"] = f"rep_{owner_key}"
        deal["rep_name"] = username
        deal["created_at"] = now - ((len(DEFAULT_DEALS) - index - 1) * 3600)
        for event in deal.get("events", []):
            if "Aarav" in event.get("description", ""):
                event["description"] = event["description"].replace("Aarav", username)
        user_deals.append(deal)
    return user_deals


def ensure_user_deals(username: str):
    if not username:
        return

    if db_connected:
        try:
            inserted = 0
            for deal in build_default_deals_for_user(username):
                if db['deals'].count_documents({"_id": deal["_id"], "owner": username}) == 0:
                    db['deals'].insert_one(deal)
                    inserted += 1
            if inserted:
                logger.info(f"Seeded {inserted} starter deals for user: {username}")
        except Exception as e:
            logger.error(f"Error seeding starter deals for user {username}: {e}")
    else:
        inserted = 0
        for deal in build_default_deals_for_user(username):
            if deal["_id"] not in mock_deals:
                mock_deals[deal["_id"]] = deal
                inserted += 1
        if inserted:
            logger.info(f"Seeded {inserted} in-memory starter deals for user: {username}")


class TriggerHTTPServer(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def send_error(self, message, status_code=400):
        self.send_json({"error": message}, status_code)

    def get_authorized_user(self) -> Optional[str]:
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None
        token = auth_header[7:].strip()
        try:
            decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            return decoded.get("username")
        except jwt.ExpiredSignatureError:
            logger.warning("JWT Token expired")
            return None
        except Exception as e:
            logger.warning(f"JWT Verification failed: {e}")
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        
        # Public Endpoint: trigger status polling
        if parsed.path == '/api/status':
            self.send_json(trigger_state)
            
        # Public Endpoint: token generator (LiveKit Room Auth)
        elif parsed.path == '/api/token':
            query = parse_qs(parsed.query)
            room = query.get('room', [''])[0]
            identity = query.get('identity', [''])[0]
            query_deal_id = query.get('deal_id', [''])[0]
            
            if not room or not identity:
                self.send_error("Missing room or identity query param", 400)
                return

            # Determine the deal_id
            deal_id = "deal_8931"
            if query_deal_id:
                deal_id = query_deal_id
            elif room == trigger_state["room_name"] and trigger_state["deal_id"]:
                deal_id = trigger_state["deal_id"]

            try:
                from livekit import api
                config = load_config()

                # Programmatically create the room and set metadata so the voice agent receives it
                try:
                    import asyncio
                    async def set_room_metadata():
                        api_url = config.livekit_url
                        if api_url.startswith("wss://"):
                            api_url = api_url.replace("wss://", "https://")
                        elif api_url.startswith("ws://"):
                            api_url = api_url.replace("ws://", "http://")
                        
                        async with api.LiveKitAPI(api_url, config.livekit_api_key, config.livekit_api_secret) as lk:
                            meta_str = json.dumps({
                                "deal_id": deal_id,
                                "rep_id": "rep_204",
                                "from_number": "direct_webrtc"
                            })
                            await lk.room.create_room(name=room, metadata=meta_str)
                            logger.info(f"Set room metadata for '{room}': {meta_str}")
                    
                    asyncio.run(set_room_metadata())
                except Exception as room_err:
                    logger.error(f"Failed to create room or set metadata via LiveKitAPI: {room_err}")
                
                token = api.AccessToken(config.livekit_api_key, config.livekit_api_secret) \
                    .with_identity(identity) \
                    .with_name(identity) \
                    .with_grants(api.VideoGrants(room_join=True, room=room)) \
                    .to_jwt()

                self.send_json({"token": token})
                logger.info(f"Generated token for room '{room}', identity '{identity}', deal '{deal_id}'")
            except Exception as e:
                logger.error(f"Error generating token: {e}")
                self.send_error(f"Error generating token: {e}", 500)
                
        # Protected Endpoint: fetch all deals
        elif parsed.path == '/api/deals':
            username = self.get_authorized_user()
            if not username:
                self.send_error("Unauthorized", 401)
                return

            query = parse_qs(parsed.query)
            try:
                page = int(query.get('page', ['1'])[0])
                limit = int(query.get('limit', ['10'])[0])
            except ValueError:
                page = 1
                limit = 10
            
            search = query.get('search', [''])[0].strip()
            sort_by = query.get('sort_by', ['created_at'])[0]
            order = query.get('order', ['desc'])[0]

            deals_list = []
            total = 0
            
            # Ensure sort_by is standard to prevent projection issues
            if sort_by not in ['name', 'amount', 'stage', 'close_date', 'created_at', 'confidence']:
                sort_by = 'created_at'

            sort_dir = -1 if order == 'desc' else 1

            if db_connected:
                try:
                    ensure_user_deals(username)
                    filter_query = {"owner": username}
                    if search:
                        filter_query["name"] = {"$regex": search, "$options": "i"}

                    deals_cursor = db['deals'].find(filter_query).sort(sort_by, sort_dir)
                    total = db['deals'].count_documents(filter_query)
                    deals_list = list(deals_cursor.skip((page - 1) * limit).limit(limit))
                except Exception as e:
                    logger.error(f"Error fetching deals from db: {e}")
            else:
                # In-memory backup
                ensure_user_deals(username)
                all_deals = [d for d in mock_deals.values() if d.get("owner") == username]
                if search:
                    all_deals = [d for d in all_deals if search.lower() in d.get('name', '').lower()]
                
                def get_sort_key(x):
                    val = x.get(sort_by)
                    if val is None:
                        return 0
                    return val

                all_deals.sort(key=get_sort_key, reverse=(order == 'desc'))
                total = len(all_deals)
                start = (page - 1) * limit
                deals_list = all_deals[start : start + limit]

            # Convert ObjectIds to strings
            for d in deals_list:
                if "_id" in d and isinstance(d["_id"], ObjectId):
                    d["_id"] = str(d["_id"])

            self.send_json({
                "data": deals_list,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total
                }
            })

        # Protected Endpoint: fetch specific deal details
        elif parsed.path.startswith('/api/deals/'):
            username = self.get_authorized_user()
            if not username:
                self.send_error("Unauthorized", 401)
                return

            deal_id = parsed.path.split('/')[-1]
            deal = None
            if db_connected:
                try:
                    deal = db['deals'].find_one({"_id": deal_id, "owner": username})
                    if not deal:
                        try:
                            deal = db['deals'].find_one({"_id": ObjectId(deal_id), "owner": username})
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Error fetching deal: {e}")
            else:
                deal = mock_deals.get(deal_id)
                if deal and deal.get("owner") != username:
                    deal = None

            if not deal:
                self.send_error("Deal not found", 404)
                return

            if "_id" in deal and isinstance(deal["_id"], ObjectId):
                deal["_id"] = str(deal["_id"])

            self.send_json(deal)
            
        else:
            self.send_error("Not found", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        
        # Public endpoint: User Registration
        if parsed.path == '/api/register':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                username = data.get("username", "").strip()
                password = data.get("password", "").strip()
            except Exception:
                self.send_error("Invalid JSON body")
                return

            if not username or not password:
                self.send_error("Username and password are required")
                return

            exists = False
            if db_connected:
                exists = db['users'].find_one({"username": username}) is not None
            else:
                exists = username in mock_users

            if exists:
                self.send_error("Username already exists", 409)
                return

            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            user_doc = {
                "username": username,
                "password_hash": password_hash,
                "created_at": time.time()
            }

            if db_connected:
                db['users'].insert_one(user_doc)
            else:
                mock_users[username] = user_doc
            ensure_user_deals(username)

            logger.info(f"User registered: {username}")
            token = jwt.encode({"username": username, "exp": time.time() + 24 * 3600}, JWT_SECRET, algorithm="HS256")
            self.send_json({
                "success": True,
                "message": "User registered successfully",
                "token": token,
                "username": username
            })

        # Public endpoint: User Login
        elif parsed.path == '/api/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                username = data.get("username", "").strip()
                password = data.get("password", "").strip()
            except Exception:
                self.send_error("Invalid JSON body")
                return

            if not username or not password:
                self.send_error("Username and password are required")
                return

            user = None
            if db_connected:
                user = db['users'].find_one({"username": username})
            else:
                user = mock_users.get(username)

            if not user or not bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
                self.send_error("Invalid username or password", 401)
                return

            ensure_user_deals(username)
            token = jwt.encode({"username": username, "exp": time.time() + 24 * 3600}, JWT_SECRET, algorithm="HS256")
            self.send_json({"token": token, "username": username})

        # Protected Endpoint: Trigger call
        elif parsed.path == '/api/trigger':
            username = self.get_authorized_user()
            if not username:
                self.send_error("Unauthorized", 401)
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data) if post_data else {}
            except Exception:
                data = {}

            trigger_state["ringing"] = True
            trigger_state["room_name"] = data.get("room_name") or f"room_{int(time.time())}"
            trigger_state["rep_id"] = data.get("rep_id") or "rep_204"
            trigger_state["deal_id"] = data.get("deal_id") or "deal_8931"
            
            logger.info(f"Trigger activated: {trigger_state}")
            self.send_json(trigger_state)

        # Protected/Public endpoint: Clear trigger
        elif parsed.path == '/api/clear':
            trigger_state["ringing"] = False
            trigger_state["room_name"] = ""
            
            logger.info("Trigger cleared")
            self.send_json(trigger_state)

        # Protected Endpoint: Create a new Deal
        elif parsed.path == '/api/deals':
            username = self.get_authorized_user()
            if not username:
                self.send_error("Unauthorized", 401)
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                name = data.get("name", "").strip()
                amount = float(data.get("amount", 0))
                stage = data.get("stage", "Discovery").strip()
                close_date = data.get("close_date", "").strip()
            except Exception:
                self.send_error("Invalid JSON body or datatypes")
                return

            if not name or not close_date:
                self.send_error("Name and close_date are required")
                return

            deal_id = f"{safe_account_id(username)}_deal_{int(time.time() * 1000)}"
            new_deal = {
                "_id": deal_id,
                "owner": username,
                "name": name,
                "amount": amount,
                "confidence": 70,
                "stage": stage,
                "close_date": close_date,
                "rep_id": f"rep_{safe_account_id(username)}",
                "rep_name": username,
                "checklist": [
                    { "id": "context", "text": "Pipeline context and AE identity confirmed", "status": "pending" },
                    { "id": "blocker", "text": "Primary deal blocker identified", "status": "pending" },
                    { "id": "security_docs", "text": "Prepare and deliver security architecture documents", "status": "pending" },
                    { "id": "stakeholder", "text": "Confirm Rohit (Economic Buyer) meeting status", "status": "pending" },
                    { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
                ],
                "tickets": [],
                "events": [
                    { "type": "deal_created", "description": f"Opportunity created in stage {stage} by {username}", "timestamp": time.time() }
                ],
                "facts": [],
                "summary": None,
                "created_at": time.time()
            }

            if db_connected:
                db['deals'].insert_one(new_deal)
            else:
                mock_deals[deal_id] = new_deal

            self.send_json(new_deal, 201)

        # Protected Endpoint: Create a new Ticket
        elif parsed.path.startswith('/api/deals/') and parsed.path.endswith('/tickets'):
            username = self.get_authorized_user()
            if not username:
                self.send_error("Unauthorized", 401)
                return

            deal_id = parsed.path.split('/')[3]
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                text = data.get("text", "").strip()
                source = data.get("source", "Manual Rep Entry").strip()
            except Exception:
                self.send_error("Invalid JSON body")
                return

            if not text:
                self.send_error("Ticket text is required")
                return

            ticket_id = f"tkt_{int(time.time() * 1000)}"
            new_ticket = {
                "id": ticket_id,
                "text": text,
                "status": "open",
                "source": source,
                "created_at": time.time()
            }

            deal = None
            if db_connected:
                # Ensure tickets list exists
                db['deals'].update_one(
                    {"_id": deal_id, "owner": username, "tickets": {"$exists": False}},
                    {"$set": {"tickets": []}}
                )
                db['deals'].update_one(
                    {"_id": deal_id, "owner": username},
                    {"$push": {
                        "tickets": new_ticket,
                        "events": {
                            "type": "ticket_created",
                            "description": f"Ticket created: {text}",
                            "timestamp": time.time()
                        }
                    }}
                )
                deal = db['deals'].find_one({"_id": deal_id, "owner": username})
                if not deal:
                    try:
                        db['deals'].update_one(
                            {"_id": ObjectId(deal_id), "owner": username, "tickets": {"$exists": False}},
                            {"$set": {"tickets": []}}
                        )
                        db['deals'].update_one(
                            {"_id": ObjectId(deal_id), "owner": username},
                            {"$push": {
                                "tickets": new_ticket,
                                "events": {
                                    "type": "ticket_created",
                                    "description": f"Ticket created: {text}",
                                    "timestamp": time.time()
                                }
                            }}
                        )
                        deal = db['deals'].find_one({"_id": ObjectId(deal_id), "owner": username})
                    except Exception:
                        pass
            else:
                deal = mock_deals.get(deal_id)
                if deal and deal.get("owner") != username:
                    deal = None
                if deal:
                    if "tickets" not in deal:
                        deal["tickets"] = []
                    deal["tickets"].append(new_ticket)
                    if "events" not in deal:
                        deal["events"] = []
                    deal["events"].append({
                        "type": "ticket_created",
                        "description": f"Ticket created: {text}",
                        "timestamp": time.time()
                    })

            if not deal:
                self.send_error("Deal not found", 404)
                return

            if "_id" in deal and isinstance(deal["_id"], ObjectId):
                deal["_id"] = str(deal["_id"])

            self.send_json(deal, 201)

        else:
            self.send_error("Not found", 404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        username = self.get_authorized_user()
        if not username:
            self.send_error("Unauthorized", 401)
            return

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            data = json.loads(post_data) if post_data else {}
        except Exception:
            self.send_error("Invalid JSON body")
            return

        # PATCH /api/deals/<deal_id>/tickets/<ticket_id>
        if parsed.path.startswith('/api/deals/') and '/tickets/' in parsed.path:
            parts = parsed.path.split('/')
            deal_id = parts[3]
            ticket_id = parts[5]

            status = data.get("status")
            if not status or status not in ["open", "resolved"]:
                self.send_error("Status field must be 'open' or 'resolved'")
                return

            deal = None
            if db_connected:
                # Find deal and update ticket status inside the array
                result = db['deals'].update_one(
                    {"_id": deal_id, "owner": username, "tickets.id": ticket_id},
                    {"$set": {
                        "tickets.$.status": status
                    }, "$push": {
                        "events": {
                            "type": "ticket_status_changed",
                            "description": f"Ticket {ticket_id} status updated to {status}",
                            "timestamp": time.time()
                        }
                    }}
                )
                if result.matched_count == 0:
                    try:
                        result = db['deals'].update_one(
                            {"_id": ObjectId(deal_id), "owner": username, "tickets.id": ticket_id},
                            {"$set": {
                                "tickets.$.status": status
                            }, "$push": {
                                "events": {
                                    "type": "ticket_status_changed",
                                    "description": f"Ticket {ticket_id} status updated to {status}",
                                    "timestamp": time.time()
                                }
                            }}
                        )
                    except Exception:
                        pass
                
                # Fetch updated deal
                deal = db['deals'].find_one({"_id": deal_id, "owner": username})
                if not deal:
                    try:
                        deal = db['deals'].find_one({"_id": ObjectId(deal_id), "owner": username})
                    except Exception:
                        pass
            else:
                deal = mock_deals.get(deal_id)
                if deal and deal.get("owner") != username:
                    deal = None
                ticket_found = False
                if deal and "tickets" in deal:
                    for tkt in deal["tickets"]:
                        if tkt["id"] == ticket_id:
                            tkt["status"] = status
                            ticket_found = True
                            if "events" not in deal:
                                deal["events"] = []
                            deal["events"].append({
                                "type": "ticket_status_changed",
                                "description": f"Ticket {ticket_id} status updated to {status}",
                                "timestamp": time.time()
                            })
                            break
                if deal and not ticket_found:
                    deal = None

            if not deal:
                self.send_error("Deal or ticket not found", 404)
                return

            if "_id" in deal and isinstance(deal["_id"], ObjectId):
                deal["_id"] = str(deal["_id"])
            
            self.send_json(deal)

        # PATCH /api/deals/<deal_id>
        elif parsed.path.startswith('/api/deals/'):
            deal_id = parsed.path.split('/')[-1]
            
            deal = None
            if db_connected:
                deal = db['deals'].find_one({"_id": deal_id, "owner": username})
                if not deal:
                    try:
                        deal = db['deals'].find_one({"_id": ObjectId(deal_id), "owner": username})
                    except Exception:
                        pass
            else:
                deal = mock_deals.get(deal_id)
                if deal and deal.get("owner") != username:
                    deal = None

            if not deal:
                self.send_error("Deal not found", 404)
                return

            if "_id" in deal and isinstance(deal["_id"], ObjectId):
                deal_id_str = str(deal["_id"])
            else:
                deal_id_str = deal_id

            update_fields = {}
            events = deal.get("events", [])
            if not isinstance(events, list):
                events = []
            
            if "stage" in data:
                old_stage = deal.get("stage", "")
                new_stage = data["stage"]
                if old_stage != new_stage:
                    update_fields["stage"] = new_stage
                    events.append({
                        "type": "stage_changed",
                        "description": f"Stage updated from {old_stage} to {new_stage}",
                        "timestamp": time.time()
                    })

            if "name" in data:
                old_name = deal.get("name", "")
                new_name = str(data["name"]).strip()
                if not new_name:
                    self.send_error("Name cannot be empty")
                    return
                if old_name != new_name:
                    update_fields["name"] = new_name
                    events.append({
                        "type": "name_changed",
                        "description": f"Opportunity renamed from {old_name} to {new_name}",
                        "timestamp": time.time()
                    })

            if "close_date" in data:
                old_close_date = deal.get("close_date", "")
                new_close_date = str(data["close_date"]).strip()
                if not new_close_date:
                    self.send_error("Close date cannot be empty")
                    return
                if old_close_date != new_close_date:
                    update_fields["close_date"] = new_close_date
                    events.append({
                        "type": "close_date_changed",
                        "description": f"Close date updated from {old_close_date} to {new_close_date}",
                        "timestamp": time.time()
                    })

            if "amount" in data:
                old_amount = deal.get("amount", 0)
                new_amount = float(data["amount"])
                if old_amount != new_amount:
                    update_fields["amount"] = new_amount
                    events.append({
                        "type": "amount_changed",
                        "description": f"Amount updated from ${old_amount:,.2f} to ${new_amount:,.2f}",
                        "timestamp": time.time()
                    })

            if "confidence" in data:
                old_conf = deal.get("confidence", 50)
                new_conf = int(data["confidence"])
                if old_conf != new_conf:
                    update_fields["confidence"] = new_conf
                    events.append({
                        "type": "confidence_changed",
                        "description": f"Confidence adjusted from {old_conf}% to {new_conf}%",
                        "timestamp": time.time()
                    })

            if update_fields:
                update_fields["events"] = events
                if db_connected:
                    db['deals'].update_one({"_id": deal["_id"], "owner": username}, {"$set": update_fields})
                    # Re-fetch
                    updated_deal = db['deals'].find_one({"_id": deal["_id"], "owner": username})
                else:
                    for k, v in update_fields.items():
                        deal[k] = v
                    mock_deals[deal_id_str] = deal
                    updated_deal = deal

                if "_id" in updated_deal and isinstance(updated_deal["_id"], ObjectId):
                    updated_deal["_id"] = str(updated_deal["_id"])
                
                self.send_json(updated_deal)
            else:
                if "_id" in deal and isinstance(deal["_id"], ObjectId):
                    deal["_id"] = str(deal["_id"])
                self.send_json(deal)

        else:
            self.send_error("Not found", 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        username = self.get_authorized_user()
        if not username:
            self.send_error("Unauthorized", 401)
            return

        if parsed.path.startswith('/api/deals/'):
            deal_id = parsed.path.split('/')[-1]
            deleted = False
            if db_connected:
                try:
                    result = db['deals'].delete_one({"_id": deal_id, "owner": username})
                    if result.deleted_count > 0:
                        deleted = True
                    else:
                        result = db['deals'].delete_one({"_id": ObjectId(deal_id), "owner": username})
                        if result.deleted_count > 0:
                            deleted = True
                except Exception as e:
                    logger.error(f"Error deleting deal from MongoDB: {e}")
            else:
                if deal_id in mock_deals and mock_deals[deal_id].get("owner") == username:
                    mock_deals.pop(deal_id)
                    deleted = True

            if deleted:
                self.send_json({"success": True, "message": "Deal deleted successfully"})
            else:
                self.send_error("Deal not found", 404)
        else:
            self.send_error("Not found", 404)


def run_server():
    seed_database()
    port = 8000
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, TriggerHTTPServer)
    logger.info(f"Trigger API server running on http://0.0.0.0:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
