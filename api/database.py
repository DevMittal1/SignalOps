import logging
import os
import time
from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI", "")

# Global variables
db_connected = False
db = None
mock_users = {}
mock_deals = {}

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
            { "id": "stakeholder", "text": "Confirm Rohit (Economic Buyer) meeting status", "status": "pending" },
            { "id": "summary", "text": "Persist findings and facts back to CRM", "status": "pending" }
        ],
        "tickets": [],
        "events": [
            { "type": "deal_created", "description": "Opportunity created in SignalOps CRM by rep Aarav", "timestamp": time.time() - 12000 }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time() - 400
    }
]

def connect_db():
    global db_connected, db
    if MONGODB_URI:
        try:
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=3000)
            client.admin.command('ping')
            db = client['signalops']
            db_connected = True
            logger.info("Connected successfully to MongoDB Atlas")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB Atlas: {e}. Falling back to in-memory database.")
    else:
        logger.warning("MONGODB_URI not set. Running with in-memory database.")

def seed_database():
    connect_db()
    
    if db_connected:
        try:
            collections = db.list_collection_names()
            if 'deals' not in collections or db['deals'].count_documents({}) == 0:
                logger.info("Seeding MongoDB with default deals...")
                for deal in DEFAULT_DEALS:
                    db['deals'].insert_one(deal.copy())
            if 'users' not in collections:
                db.create_collection('users')
                
        except Exception as e:
            logger.error(f"Failed to seed MongoDB: {e}")
    else:
        if not mock_deals:
            logger.info("Seeding in-memory database with default deals...")
            for deal in DEFAULT_DEALS:
                mock_deals[deal["_id"]] = deal.copy()

def get_database():
    """Dependency for getting DB"""
    return db if db_connected else mock_deals
