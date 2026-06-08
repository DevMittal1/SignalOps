from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str

class VerifyRequest(BaseModel):
    username: str
    otp: str

class DealCreateRequest(BaseModel):
    name: str
    amount: float = 0
    stage: str = "Discovery"
    close_date: str

class DealUpdateRequest(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    stage: Optional[str] = None
    close_date: Optional[str] = None
    confidence: Optional[int] = None

class TicketCreateRequest(BaseModel):
    title: str
    description: str
    assignee: str
    priority: str = "medium"
    status: str = "open"

class TriggerRequest(BaseModel):
    room_name: Optional[str] = None
    rep_id: Optional[str] = None
    deal_id: Optional[str] = None
