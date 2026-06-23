import sys
import traceback
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from services.report_service import ReportService
svc = ReportService()
try:
    svc.generate({"pdf_path": "test.pdf", "text": "test text", "pdf_validation": []})
except Exception as e:
    traceback.print_exc()
