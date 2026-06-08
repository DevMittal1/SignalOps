from fastapi import APIRouter, Depends
from typing import Optional
from ..schemas import DealCreateRequest, DealUpdateRequest, TicketCreateRequest
from ..services import deal_service
from ..dependencies import get_db, get_current_user

router = APIRouter()

@router.get("")
def get_deals(
    limit: int = 100, 
    skip: int = 0, 
    search: str = "", 
    sort_by: str = "created_at", 
    order: str = "desc",
    username: str = Depends(get_current_user),
    db=Depends(get_db)
):
    return deal_service.get_all_deals(username, db, limit, skip, search, sort_by, order)

@router.get("/{deal_id}")
def get_deal(deal_id: str, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.get_deal_by_id(username, deal_id, db)

@router.post("")
def create_deal(data: DealCreateRequest, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.create_deal(username, data, db)

@router.patch("/{deal_id}")
def update_deal(deal_id: str, data: DealUpdateRequest, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.update_deal(username, deal_id, data, db)

@router.delete("/{deal_id}")
def delete_deal(deal_id: str, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.delete_deal(username, deal_id, db)

@router.post("/{deal_id}/tickets")
def create_ticket(deal_id: str, data: TicketCreateRequest, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.create_ticket(username, deal_id, data, db)

@router.patch("/{deal_id}/tickets/{ticket_id}")
def update_ticket(deal_id: str, ticket_id: str, status: str, username: str = Depends(get_current_user), db=Depends(get_db)):
    return deal_service.update_ticket(username, deal_id, ticket_id, status, db)
