from fastapi import APIRouter, Depends
from ..schemas import TriggerRequest
from ..services import livekit_service
from ..dependencies import get_current_user
from ..database import trigger_state

router = APIRouter()

@router.get("/status")
def get_status():
    return trigger_state

@router.post("/trigger")
def trigger_call(data: TriggerRequest, username: str = Depends(get_current_user)):
    return livekit_service.update_trigger_state(data)

@router.post("/clear")
def clear_trigger():
    return livekit_service.clear_trigger_state()
