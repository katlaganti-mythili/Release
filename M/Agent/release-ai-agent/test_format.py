import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.report_service import MASTER_PROMPT

try:
    formatted = MASTER_PROMPT.format(
        current_date="123",
        system_determined_latest_version="456",
        system_determined_release_type="789",
        system_determined_date_validation="abc",
        system_determined_jira_tickets="def"
    )
    print("SUCCESS")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"FAILED: {repr(e)}")
