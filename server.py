import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import load_config
from monitoring.logger import setup_logging
from api.database import seed_database
from api.routers import auth, deals, trigger, token

config = load_config()

setup_logging(
    log_dir=config.log_dir,
    log_level=config.log_level,
    json_logs=config.json_logs,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="SignalOps API", description="FastAPI Server for SignalOps CRM and Voice AI trigger")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup DB on startup
@app.on_event("startup")
async def startup_event():
    logger.info("Initializing API Server...")
    seed_database()

# Include Routers
app.include_router(auth.router, prefix="/api")
app.include_router(deals.router, prefix="/api/deals")
app.include_router(trigger.router, prefix="/api")
app.include_router(token.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
