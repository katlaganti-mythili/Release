import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.validators.jira_excel_validator import JiraExcelValidator

validator = JiraExcelValidator()

excel_path = "dummy.xlsx"

# Test 1: Can we read the excel?
print("--- TESTING EXCEL EXTRACTION ---")
records = validator.read_excel(excel_path)
print(f"Total records found in excel: {len(records)}")
if len(records) > 0:
    print(f"Sample record: {records[0]}")
else:
    print("Failed to read any records from Excel.")

# We don't have the original PDFs to test PDF extraction easily, but we can test the filtering
print("\n--- TESTING APPLICATION FILTERING ---")
# Let's see what unique applications were found in the excel
apps = set(r.get("application", "") for r in records)
print(f"Applications found in excel: {apps}")

# Try filtering by one of them
if apps:
    sample_app = list(apps)[0]
    filtered = validator.filter_application_records(records, sample_app)
    print(f"Records after filtering for '{sample_app}': {len(filtered)}")

