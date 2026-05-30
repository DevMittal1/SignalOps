"""
Twilio Integration Layer
- SIP trunk provisioning
- Inbound call webhooks → LiveKit room dispatch
- Outbound call initiation
- Call status callbacks
"""

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import Response as FastAPIResponse
from livekit import api as lk_api

logger = logging.getLogger(__name__)

app = FastAPI(title="Twilio-LiveKit Bridge", version="1.0.0")


class TwilioLiveKitBridge:
    def __init__(self):
        self.twilio_auth_token = os.environ["TWILIO_AUTH_TOKEN"]
        self.twilio_account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        self.livekit_url = os.environ["LIVEKIT_URL"]
        self.livekit_api_key = os.environ["LIVEKIT_API_KEY"]
        self.livekit_api_secret = os.environ["LIVEKIT_API_SECRET"]
        self.webhook_base_url = os.environ["WEBHOOK_BASE_URL"]

        self._lk_client = lk_api.LiveKitAPI(
            url=self.livekit_url,
            api_key=self.livekit_api_key,
            api_secret=self.livekit_api_secret,
        )

    def validate_twilio_signature(self, url: str, params: dict, signature: str) -> bool:
        """Validate that webhook came from Twilio."""
        s = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        computed = hmac.new(
            self.twilio_auth_token.encode("utf-8"),
            s.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        import base64
        expected = base64.b64encode(computed).decode()
        return hmac.compare_digest(expected, signature)

    async def create_livekit_room_for_call(
        self,
        call_sid: str,
        from_number: str,
        to_number: str,
    ) -> tuple[str, str]:
        """Create LiveKit room and dispatch agent job."""
        room_name = f"call-{call_sid}"

        metadata = json.dumps({
            "call_sid": call_sid,
            "from_number": from_number,
            "to_number": to_number,
            "source": "twilio",
        })

        # Create room
        await self._lk_client.room.create_room(
            lk_api.CreateRoomRequest(
                name=room_name,
                empty_timeout=300,
                metadata=metadata,
            )
        )

        # Dispatch agent worker to the room
        await self._lk_client.agent_dispatch.create_dispatch(
            lk_api.RoomAgentDispatch(
                agent_name="voice-ai-agent",
                room_name=room_name,
                metadata=metadata,
            )
        )

        # Generate SIP participant token for Twilio to join
        token = (
            lk_api.AccessToken(self.livekit_api_key, self.livekit_api_secret)
            .with_identity(f"twilio-{call_sid}")
            .with_name(f"Caller {from_number}")
            .with_grants(
                lk_api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                )
            )
            .to_jwt()
        )

        return room_name, token

    def build_twiml_connect_sip(self, room_name: str, token: str) -> str:
        """Generate TwiML to connect Twilio call into LiveKit via SIP."""
        sip_uri = f"sip:{room_name}@{self._extract_sip_host()}"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{self._extract_ws_host()}/twilio-stream">
      <Parameter name="room_name" value="{room_name}"/>
      <Parameter name="token" value="{token}"/>
    </Stream>
  </Connect>
</Response>"""

    def _extract_sip_host(self) -> str:
        return self.livekit_url.replace("wss://", "").replace("https://", "")

    def _extract_ws_host(self) -> str:
        return self.webhook_base_url.replace("https://", "")

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        agent_metadata: Optional[dict] = None,
    ) -> dict:
        """Initiate outbound call from Twilio → LiveKit agent."""
        async with httpx.AsyncClient() as client:
            twiml_url = f"{self.webhook_base_url}/twilio/outbound-answer"
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/Calls.json",
                auth=(self.twilio_account_sid, self.twilio_auth_token),
                data={
                    "To": to_number,
                    "From": from_number,
                    "Url": twiml_url,
                    "StatusCallback": f"{self.webhook_base_url}/twilio/status",
                    "StatusCallbackMethod": "POST",
                    "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
                    "Record": "false",
                },
            )
            resp.raise_for_status()
            call_data = resp.json()
            logger.info(f"Outbound call initiated | SID={call_data['sid']} | To={to_number}")
            return call_data


# --- Singleton bridge instance ---
bridge = TwilioLiveKitBridge()


# ─── Webhook Routes ─────────────────────────────────────────────────────────

@app.post("/twilio/inbound", response_class=FastAPIResponse)
async def handle_inbound_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    x_twilio_signature: str = Header(None, alias="X-Twilio-Signature"),
):
    """
    Twilio calls this when an inbound call arrives.
    Creates LiveKit room, dispatches agent, returns TwiML to connect caller.
    """
    logger.info(f"Inbound call | SID={CallSid} | From={From} | To={To}")

    try:
        room_name, token = await bridge.create_livekit_room_for_call(
            call_sid=CallSid,
            from_number=From,
            to_number=To,
        )
        twiml = bridge.build_twiml_connect_sip(room_name, token)
        return FastAPIResponse(content=twiml, media_type="text/xml")

    except Exception as e:
        logger.error(f"Failed to handle inbound call {CallSid}: {e}", exc_info=True)
        fallback_twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>We're sorry, all agents are currently unavailable. Please try again later.</Say>
  <Hangup/>
</Response>"""
        return FastAPIResponse(content=fallback_twiml, media_type="text/xml", status_code=200)


@app.post("/twilio/status")
async def handle_call_status(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: Optional[str] = Form(None),
    To: str = Form(...),
    From: str = Form(...),
):
    """Twilio status callbacks — log call lifecycle events."""
    logger.info(
        f"Call status | SID={CallSid} | Status={CallStatus} | "
        f"Duration={CallDuration}s | From={From} | To={To}"
    )

    if CallStatus == "completed" and CallDuration:
        logger.info(f"Call completed | SID={CallSid} | Duration={CallDuration}s")

    return {"status": "ok"}


@app.post("/twilio/outbound-answer")
async def handle_outbound_answer(
    CallSid: str = Form(...),
    To: str = Form(...),
    From: str = Form(...),
):
    """TwiML response for outbound calls when recipient answers."""
    room_name, token = await bridge.create_livekit_room_for_call(
        call_sid=CallSid,
        from_number=From,
        to_number=To,
    )
    twiml = bridge.build_twiml_connect_sip(room_name, token)
    return FastAPIResponse(content=twiml, media_type="text/xml")


@app.post("/api/call/outbound")
async def initiate_outbound(request: Request):
    """REST API to trigger an outbound call."""
    body = await request.json()
    to_number = body.get("to")
    from_number = body.get("from") or os.environ.get("TWILIO_PHONE_NUMBER")

    if not to_number:
        raise HTTPException(status_code=400, detail="'to' phone number required")

    result = await bridge.initiate_outbound_call(
        to_number=to_number,
        from_number=from_number,
        agent_metadata=body.get("metadata"),
    )
    return {"call_sid": result["sid"], "status": result["status"]}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": time.time()}
