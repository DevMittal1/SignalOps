import json
import logging
from fastapi import HTTPException
from ..database import trigger_state

logger = logging.getLogger(__name__)

async def generate_token(room: str, identity: str, query_deal_id: str):
    if not room or not identity:
        raise HTTPException(status_code=400, detail="Missing room or identity query param")

    # Determine the deal_id
    deal_id = "deal_8931"
    if query_deal_id:
        deal_id = query_deal_id
    elif room == trigger_state["room_name"] and trigger_state["deal_id"]:
        deal_id = trigger_state["deal_id"]

    try:
        from livekit import api
        import asyncio
        from config.settings import load_config
        config = load_config()

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
                await lk.room.create_room(api.CreateRoomRequest(name=room, metadata=meta_str))
                logger.info(f"Set room metadata for '{room}': {meta_str}")
        
        await set_room_metadata()
        
        token = api.AccessToken(config.livekit_api_key, config.livekit_api_secret) \
            .with_identity(identity) \
            .with_name(identity) \
            .with_grants(api.VideoGrants(room_join=True, room=room)) \
            .to_jwt()

        logger.info(f"Generated token for room '{room}', identity '{identity}', deal '{deal_id}'")
        return {"token": token}
    except Exception as e:
        logger.error(f"Error generating token: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating token: {e}")

def update_trigger_state(data):
    import time
    trigger_state["ringing"] = True
    trigger_state["room_name"] = data.room_name or f"room_{int(time.time())}"
    trigger_state["rep_id"] = data.rep_id or "rep_204"
    trigger_state["deal_id"] = data.deal_id or "deal_8931"
    
    logger.info(f"Trigger activated: {trigger_state}")
    return trigger_state

def clear_trigger_state():
    trigger_state["ringing"] = False
    trigger_state["room_name"] = ""
    logger.info("Trigger cleared")
    return trigger_state
