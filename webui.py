# ==============================================================================
# FILE: webui.py
# PURPOSE: Web User Interface (V4 Future). Currently holds the Docker 
#          Healthcheck server. In the future, this will host the web dashboard
#          to manage config.yml and view system statistics.
# VARIABLES/DEPENDENCIES: http.server for basic responses. Future: Flask/FastAPI.
# ==============================================================================

from http.server import BaseHTTPRequestHandler, HTTPServer
import logging

# Import all settings from config.py (Useful for V4 WebUI future update)
from config import *

# Initialize the logger for this specific module
logger = logging.getLogger(__name__)

# ==============================================================================
# DOCKER HEALTHCHECK SERVER
# ==============================================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Respond with 200 OK so Docker knows the script hasn't crashed."""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
        
    def log_message(self, format, *args):
        """Hide healthcheck pings from the logs to keep it clean."""
        pass 

def healthcheck_thread():
    """Runs a tiny web server on port 8080 inside the container."""
    try:
        server = HTTPServer(('0.0.0.0', 8080), HealthCheckHandler)
        server.serve_forever()
    except Exception as e:
        logger.error(f"Healthcheck Server Error: {e}")
