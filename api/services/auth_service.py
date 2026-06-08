import bcrypt
import jwt
import time
import os
import random
import resend
from fastapi import HTTPException
from ..schemas import LoginRequest, RegisterRequest, VerifyRequest

JWT_SECRET = os.getenv("JWT_SECRET", "signalops-super-jwt-secret-key-2026")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
resend.api_key = RESEND_API_KEY

def ensure_user_deals(username, db):
    """Seed user deals if none exist"""
    # Import locally to avoid circular dependencies
    from .deal_service import seed_initial_deals_for_user
    seed_initial_deals_for_user(username, db)

def register_user(request: RegisterRequest, db):
    username = request.username.strip()
    password = request.password.strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    exists = False
    if isinstance(db, dict): # Mock DB
        exists = username in db.get("users", {})
    else: # MongoDB
        exists = db['users'].find_one({"username": username}) is not None

    if exists:
        raise HTTPException(status_code=409, detail="Username already exists")

    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    otp = str(random.randint(100000, 999999))
    
    user_doc = {
        "username": username,
        "password_hash": password_hash,
        "created_at": time.time(),
        "verified": False,
        "otp": otp,
        "otp_expires": time.time() + 600  # 10 minutes
    }

    if isinstance(db, dict):
        if "users" not in db:
            db["users"] = {}
        db["users"][username] = user_doc
    else:
        db['users'].insert_one(user_doc)
        
    # Send email
    if resend.api_key:
        try:
            resend.Emails.send({
                "from": "onboarding@resend.dev",
                "to": username,
                "subject": "SignalOps - Verify your email",
                "html": f"<p>Your verification code is: <strong>{otp}</strong></p><p>This code expires in 10 minutes.</p>"
            })
        except Exception as e:
            print(f"Failed to send email: {e}")
            
    return {"status": "pending_verification", "message": "OTP sent to email", "username": username}

def verify_user(request: VerifyRequest, db):
    username = request.username.strip()
    otp = request.otp.strip()

    if not username or not otp:
        raise HTTPException(status_code=400, detail="Username and OTP are required")

    if isinstance(db, dict):
        user = db.get("users", {}).get(username)
    else:
        user = db['users'].find_one({"username": username})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("verified"):
        raise HTTPException(status_code=400, detail="User is already verified")

    if user.get("otp") != otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    if user.get("otp_expires", 0) < time.time():
        raise HTTPException(status_code=400, detail="OTP has expired")

    # Mark as verified
    if isinstance(db, dict):
        db["users"][username]["verified"] = True
        db["users"][username]["otp"] = None
    else:
        db['users'].update_one({"username": username}, {"$set": {"verified": True}, "$unset": {"otp": "", "otp_expires": ""}})

    # Now populate CRM data
    ensure_user_deals(username, db)
    
    token = jwt.encode({"username": username, "exp": time.time() + 24 * 3600}, JWT_SECRET, algorithm="HS256")
    return {"token": token, "username": username}

def login_user(request: LoginRequest, db):
    username = request.username.strip()
    password = request.password.strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = None
    if isinstance(db, dict):
        user = db.get("users", {}).get(username)
    else:
        user = db['users'].find_one({"username": username})

    if not user or not bcrypt.checkpw(password.encode('utf-8'), user["password_hash"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    if not user.get("verified", False):
        raise HTTPException(status_code=403, detail="Account not verified. Please verify your email.")

    ensure_user_deals(username, db)
    token = jwt.encode({"username": username, "exp": time.time() + 24 * 3600}, JWT_SECRET, algorithm="HS256")
    return {"token": token, "username": username}
