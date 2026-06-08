from fastapi import APIRouter, Query
from ..services import livekit_service

router = APIRouter()

@router.get("/token")
async def get_token(
    room: str = Query(""), 
    identity: str = Query(""), 
    deal_id: str = Query("")
):
    return await livekit_service.generate_token(room, identity, deal_id)
