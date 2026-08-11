import os
import fitz
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class PDFValidator:
    def __init__(self, retries: int = 2, backoff: float = 0.5):
        # Create a session with simple retry logic for transient network failures
        self.session = requests.Session()
        retry = Retry(total=retries, backoff_factor=backoff, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["HEAD", "GET"])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def validate(self, paths: list):
        results = []

        for path in paths:
            clean_path = urllib.parse.unquote(urllib.parse.unquote(path))
            
            is_url = isinstance(clean_path, str) and clean_path.lower().startswith(("http://", "https://"))
            
            if not is_url:
                if clean_path.startswith("file:///"):
                    clean_path = clean_path[8:]
                elif clean_path.startswith("file://"):
                    clean_path = clean_path[7:]
                elif clean_path.startswith("file:/"):
                    clean_path = clean_path[6:]
                    
                if os.name == 'nt' and clean_path.startswith('/') and len(clean_path) > 2 and clean_path[2] == ':':
                    clean_path = clean_path[1:]
                    
                if os.name == 'nt':
                    clean_path = os.path.normpath(clean_path)

            result = {
                "file_path": clean_path,
                "original_link": path,
                "exists": False,
                "readable": False,
                "status": "FAIL",
                "error": None,
                "http_status": None,
            }

            if is_url:
                try:
                    # Prefer HEAD; fall back to GET when servers block HEAD
                    response = self.session.head(clean_path, allow_redirects=True, timeout=10)
                    if response.status_code in (403, 405):
                        response = self.session.get(clean_path, stream=True, timeout=10)

                    result["http_status"] = getattr(response, "status_code", None)

                    # Treat only 2xx-3xx as existing/available
                    if 200 <= response.status_code < 400:
                        result["exists"] = True
                        result["readable"] = True
                        result["status"] = "PASS"
                    else:
                        # Non-success HTTP responses are treated as not available for our purposes
                        result["exists"] = False
                        result["error"] = f"HTTP Error {response.status_code}"
                except requests.RequestException as e:
                    # Capture status if available on the exception's response
                    try:
                        result["http_status"] = e.response.status_code if getattr(e, 'response', None) is not None else None
                    except Exception:
                        result["http_status"] = None
                    result["error"] = str(e)
            else:
                try:
                    exists = os.path.exists(clean_path)
                except OSError as e:
                    exists = False
                    result["error"] = f"Invalid path format: {e}"

                if exists:
                    result["exists"] = True

                    try:
                        with open(clean_path, "rb") as f:
                            pdf_bytes = f.read()
                        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                            _ = len(doc)

                        result["readable"] = True
                        result["status"] = "PASS"

                    except Exception as e:
                        result["error"] = str(e)

                elif not result["error"]:
                    result["error"] = "File not found"

            results.append(result)

        return results
