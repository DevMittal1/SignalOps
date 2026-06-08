from fastapi import APIRouter, Depends
from ..schemas import LoginRequest, RegisterRequest, VerifyRequest
from ..services import auth_service
from ..dependencies import get_db

router = APIRouter()

@router.post("/register")
def register(request: RegisterRequest, db=Depends(get_db)):
    return auth_service.register_user(request, db)

@router.post("/verify")
def verify(request: VerifyRequest, db=Depends(get_db)):
    return auth_service.verify_user(request, db)

@router.post("/login")
def login(request: LoginRequest, db=Depends(get_db)):
    return auth_service.login_user(request, db)
