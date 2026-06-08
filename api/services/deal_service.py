import time
import json
import re
import logging
import uuid
from bson import ObjectId
from fastapi import HTTPException
from ..database import DEFAULT_DEALS

logger = logging.getLogger(__name__)

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

def seed_initial_deals_for_user(username: str, db):
    if not username:
        return

    if not isinstance(db, dict): # MongoDB
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
    else: # Mock
        inserted = 0
        for deal in build_default_deals_for_user(username):
            if deal["_id"] not in db:
                db[deal["_id"]] = deal
                inserted += 1
        if inserted:
            logger.info(f"Seeded {inserted} in-memory starter deals for user: {username}")

def get_all_deals(username: str, db, limit: int = 100, skip: int = 0, search: str = "", sort_by: str = "created_at", order: str = "desc"):
    if not isinstance(db, dict):
        query = {"owner": username}
        if search:
            query["name"] = {"$regex": search, "$options": "i"}
        
        sort_direction = -1 if order == "desc" else 1
        deals_cursor = db['deals'].find(query).sort(sort_by, sort_direction).skip(skip).limit(limit)
        
        deals_list = []
        for deal in deals_cursor:
            if "_id" in deal and isinstance(deal["_id"], ObjectId):
                deal["_id"] = str(deal["_id"])
            deals_list.append(deal)
        return deals_list
    else:
        # Mock logic
        user_deals = [d for d in db.values() if d.get("owner") == username]
        if search:
            user_deals = [d for d in user_deals if search.lower() in d.get("name", "").lower()]
        
        user_deals.sort(key=lambda x: x.get(sort_by, 0), reverse=(order == "desc"))
        return user_deals[skip:skip+limit]

def get_deal_by_id(username: str, deal_id: str, db):
    if not isinstance(db, dict):
        deal = db['deals'].find_one({"_id": deal_id, "owner": username})
        if not deal:
            try:
                deal = db['deals'].find_one({"_id": ObjectId(deal_id), "owner": username})
            except Exception:
                pass
    else:
        deal = db.get(deal_id)
        if deal and deal.get("owner") != username:
            deal = None

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if "_id" in deal and isinstance(deal["_id"], ObjectId):
        deal["_id"] = str(deal["_id"])
        
    return deal

def create_deal(username: str, data, db):
    deal_id = f"{safe_account_id(username)}_deal_{int(time.time() * 1000)}"
    new_deal = {
        "_id": deal_id,
        "owner": username,
        "name": data.name,
        "amount": data.amount,
        "confidence": 70,
        "stage": data.stage,
        "close_date": data.close_date,
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
            {
                "type": "deal_created",
                "description": f"Opportunity created in SignalOps CRM by rep {username}",
                "timestamp": time.time()
            }
        ],
        "facts": [],
        "summary": None,
        "created_at": time.time()
    }

    if not isinstance(db, dict):
        db['deals'].insert_one(new_deal.copy())
    else:
        db[deal_id] = new_deal.copy()

    return new_deal

def update_deal(username: str, deal_id: str, data, db):
    deal = get_deal_by_id(username, deal_id, db)
    deal_id_str = deal["_id"]
    
    update_fields = {}
    events = deal.get("events", [])
    
    if data.stage is not None and deal.get("stage", "") != data.stage:
        update_fields["stage"] = data.stage
        events.append({"type": "stage_changed", "description": f"Stage updated to {data.stage}", "timestamp": time.time()})
        
    if data.name is not None and data.name.strip() and deal.get("name", "") != data.name.strip():
        update_fields["name"] = data.name.strip()
        events.append({"type": "name_changed", "description": f"Renamed to {data.name}", "timestamp": time.time()})
        
    if data.close_date is not None and data.close_date.strip() and deal.get("close_date", "") != data.close_date.strip():
        update_fields["close_date"] = data.close_date.strip()
        events.append({"type": "close_date_changed", "description": f"Close date updated to {data.close_date}", "timestamp": time.time()})
        
    if data.amount is not None and deal.get("amount", 0) != data.amount:
        update_fields["amount"] = data.amount
        events.append({"type": "amount_changed", "description": f"Amount updated to ${data.amount:,.2f}", "timestamp": time.time()})
        
    if data.confidence is not None and deal.get("confidence", 50) != data.confidence:
        update_fields["confidence"] = data.confidence
        events.append({"type": "confidence_changed", "description": f"Confidence adjusted to {data.confidence}%", "timestamp": time.time()})

    if update_fields:
        update_fields["events"] = events
        if not isinstance(db, dict):
            # If id is obj string
            db['deals'].update_one({"_id": deal_id_str, "owner": username}, {"$set": update_fields})
            # Refetch
            updated = get_deal_by_id(username, deal_id_str, db)
            return updated
        else:
            for k, v in update_fields.items():
                deal[k] = v
            db[deal_id_str] = deal
            return deal
    return deal

def delete_deal(username: str, deal_id: str, db):
    deleted = False
    if not isinstance(db, dict):
        result = db['deals'].delete_one({"_id": deal_id, "owner": username})
        if result.deleted_count > 0:
            deleted = True
        else:
            try:
                result = db['deals'].delete_one({"_id": ObjectId(deal_id), "owner": username})
                if result.deleted_count > 0:
                    deleted = True
            except:
                pass
    else:
        if deal_id in db and db[deal_id].get("owner") == username:
            db.pop(deal_id)
            deleted = True

    if not deleted:
        raise HTTPException(status_code=404, detail="Deal not found")
    return {"success": True, "message": "Deal deleted successfully"}

def create_ticket(username: str, deal_id: str, data, db):
    deal = get_deal_by_id(username, deal_id, db)
    
    new_ticket = {
        "id": f"tkt_{str(uuid.uuid4())[:8]}",
        "title": data.title,
        "description": data.description,
        "status": data.status,
        "priority": data.priority,
        "assignee": data.assignee,
        "created_at": time.time()
    }
    
    if not isinstance(db, dict):
        db['deals'].update_one(
            {"_id": deal["_id"]},
            {"$push": {
                "tickets": new_ticket,
                "events": {
                    "type": "ticket_created",
                    "description": f"Ticket created: {data.title}",
                    "timestamp": time.time()
                }
            }}
        )
        return get_deal_by_id(username, deal["_id"], db)
    else:
        if "tickets" not in deal:
            deal["tickets"] = []
        deal["tickets"].append(new_ticket)
        if "events" not in deal:
            deal["events"] = []
        deal["events"].append({
            "type": "ticket_created",
            "description": f"Ticket created: {data.title}",
            "timestamp": time.time()
        })
        return deal

def update_ticket(username: str, deal_id: str, ticket_id: str, status: str, db):
    deal = get_deal_by_id(username, deal_id, db)
    
    if not isinstance(db, dict):
        result = db['deals'].update_one(
            {"_id": deal["_id"], "tickets.id": ticket_id},
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
        return get_deal_by_id(username, deal["_id"], db)
    else:
        for tkt in deal.get("tickets", []):
            if tkt["id"] == ticket_id:
                tkt["status"] = status
                if "events" not in deal:
                    deal["events"] = []
                deal["events"].append({
                    "type": "ticket_status_changed",
                    "description": f"Ticket {ticket_id} status updated to {status}",
                    "timestamp": time.time()
                })
        return deal
