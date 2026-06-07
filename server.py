import os
import sys
import time
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from config.settings import load_config

# Set up simple logging for the server
logging.basicConfig(level=logging.INFO, format="[Server] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Shared global state
trigger_state = {
    "ringing": False,
    "room_name": "",
    "rep_id": "rep_204",
    "deal_id": "deal_8931"
}


class TriggerHTTPServer(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(trigger_state).encode('utf-8'))
        elif parsed.path == '/api/token':
            query = parse_qs(parsed.query)
            room = query.get('room', [''])[0]
            identity = query.get('identity', [''])[0]
            if not room or not identity:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing room or identity query param")
                return

            try:
                from livekit import api
                config = load_config()
                
                token = api.AccessToken(config.livekit_api_key, config.livekit_api_secret) \
                    .with_identity(identity) \
                    .with_name(identity) \
                    .with_grants(api.VideoGrants(room_join=True, room=room)) \
                    .to_jwt()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"token": token}).encode('utf-8'))
                logger.info(f"Generated token for room '{room}' and identity '{identity}'")
            except Exception as e:
                logger.error(f"Error generating token: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error generating token: {e}".encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/trigger':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data) if post_data else {}
            except Exception:
                data = {}

            trigger_state["ringing"] = True
            trigger_state["room_name"] = data.get("room_name") or f"room_{int(time.time())}"
            trigger_state["rep_id"] = data.get("rep_id") or "rep_204"
            trigger_state["deal_id"] = data.get("deal_id") or "deal_8931"
            
            logger.info(f"Trigger activated: {trigger_state}")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(trigger_state).encode('utf-8'))

        elif parsed.path == '/api/clear':
            trigger_state["ringing"] = False
            trigger_state["room_name"] = ""
            
            logger.info("Trigger cleared")

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(trigger_state).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()


def run_server():
    port = 8000
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, TriggerHTTPServer)
    logger.info(f"Trigger API server running on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API server...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
