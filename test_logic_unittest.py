import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import fitz

from agents.version_validator import VersionValidator
from agents.pdf_validator import PDFValidator
from agents.validators.toc_validator import TOCValidator
from core.state import ReleaseState
from core.nodes import validate_pdfs, validate_excel
from services.report_service import ReportService


class ReportServiceTests(unittest.TestCase):
    def test_generate_uses_matching_build_block_for_report_inputs(self):
        captured = {}
        service = ReportService()
        service.llm = type(
            "PromptCapture",
            (),
            {"ask": lambda self, prompt: captured.setdefault("prompt", prompt) or prompt},
        )()
        service.jira_service = type(
            "JiraStub",
            (),
            {"ticket_exists": lambda self, ticket: (True, "")},
        )()

        text = (
            "Appendix A\n"
            "Build Number: ARM 1.0.0.0; 01-01-2024\n"
            "patch\n"
            "MNOSD-1\n"
            "Appendix B\n"
            "Build Number: ARM 2.0.0.0; 06-21-2026\n"
            "hotfix\n"
            "MNOSD-2"
        )

        report_text, _ = service.generate(
            {
                "pdf_path": "C:/tmp/OpenGrid 2.0.0.0 Product Release Notes.pdf",
                "text": text,
                "pdf_validation": [],
                "system_determined_latest_version": "2.0.0.0",
            },
            output_path="reports/_tmp_validation.txt",
        )

        self.assertIn("Found date: 06-21-2026", report_text)
        self.assertIn("- SSC ID found (2.0.0.0): MNOSD-2 [Verified in Jira]", report_text)
        self.assertIn("- **Release Type:** HOTFIX", report_text)

    def test_generate_includes_pdf_link_summary_counts(self):
        service = ReportService()
        service.llm = type(
            "PromptCapture",
            (),
            {"ask": lambda self, prompt: prompt},
        )()
        service.jira_service = type(
            "JiraStub",
            (),
            {"ticket_exists": lambda self, ticket: (True, "")},
        )()

        report_text, _ = service.generate(
            {
                "pdf_path": "C:/tmp/OpenGrid 1.0.0.0 Product Release Notes.pdf",
                "text": "",
                "pdf_validation": [
                    {"file_path": "C:/tmp/a.pdf", "raw_text": "a.pdf", "exists": True, "readable": True, "status": "PASS", "error": None},
                    {"file_path": "C:/tmp/b.pdf", "raw_text": "b.pdf", "exists": False, "readable": False, "status": "FAIL", "error": "File not found"},
                    {"file_path": "C:/tmp/c.pdf", "raw_text": "c.pdf", "exists": True, "readable": False, "status": "FAIL", "error": "Failed to open"},
                ],
                "system_determined_latest_version": "1.0.0.0",
            },
            output_path="reports/_tmp_validation.txt",
        )

        self.assertIn("- **Successfully opened:** 1 | **Missing:** 1 | **Exists but failed to open:** 1", report_text)

    def test_extract_build_blocks_preserves_full_ticket_ids(self):
        service = ReportService()
        text = (
            "Appendix A\n"
            "Build Number: ARM 2.0.0.0; 06-21-2026\n"
            "MNOSD-1234-5678\n"
            "WAMAT- 9876 - 5432\n"
            "WAMAT-4301A\n"
        )

        blocks = service.extract_build_blocks(text)
        all_tickets = set()
        for block in blocks.values():
            all_tickets.update(block.get("tickets", []))

        self.assertIn("MNOSD-1234-5678", all_tickets)
        self.assertIn("WAMAT-9876-5432", all_tickets)
        self.assertIn("WAMAT-4301A", all_tickets)

    def test_extract_build_blocks_strips_bug_swg_suffixes(self):
        service = ReportService()
        text = (
            "Appendix A\n"
            "Build Number: ARM 2.3.15.0[0]; 08-07-2026\n"
            "MNOSD-26209BUG\n"
            "WAMAT-77335\n"
            "MNOSD-28076SWG\n"
        )

        blocks = service.extract_build_blocks(text)
        all_tickets = set()
        for block in blocks.values():
            all_tickets.update(block.get("tickets", []))

        self.assertIn("MNOSD-26209", all_tickets)
        self.assertIn("MNOSD-28076", all_tickets)
        self.assertIn("WAMAT-77335", all_tickets)
        self.assertNotIn("MNOSD-26209BUG", all_tickets)
        self.assertNotIn("MNOSD-28076SWG", all_tickets)


class NodesValidationTests(unittest.TestCase):
    def test_validate_pdfs_records_exception_for_failed_link(self):
        state = ReleaseState()
        state.resolved_links = [
            {"original_link": "a.pdf", "resolved_path": "a.pdf", "raw_text": "a.pdf"},
            {"original_link": "bad.pdf", "resolved_path": "bad.pdf", "raw_text": "bad.pdf"},
        ]

        class FakeValidator:
            def validate(self, paths):
                if paths[0] == "bad.pdf":
                    raise RuntimeError("Unexpected validation error")
                return [{
                    "file_path": paths[0],
                    "original_link": paths[0],
                    "exists": True,
                    "readable": True,
                    "status": "PASS",
                    "error": None,
                }]

        with patch("agents.pdf_validator.PDFValidator", new=FakeValidator):
            result = validate_pdfs(state)

        self.assertEqual(len(result["pdf_validation"]), 2)
        mapped = {item["original_link"]: item for item in result["pdf_validation"]}

        self.assertTrue(mapped["a.pdf"]["exists"])
        self.assertTrue(mapped["a.pdf"]["readable"])
        self.assertEqual(mapped["a.pdf"]["status"], "PASS")

        self.assertFalse(mapped["bad.pdf"]["exists"])
        self.assertFalse(mapped["bad.pdf"]["readable"])
        self.assertEqual(mapped["bad.pdf"]["status"], "FAIL")
        self.assertIn("Exception during validation", mapped["bad.pdf"]["error"])

    def test_validate_pdfs_uses_adaptive_max_workers(self):
        state = ReleaseState()
        state.resolved_links = [
            {"original_link": "a.pdf", "resolved_path": "a.pdf", "raw_text": "a.pdf"},
            {"original_link": "b.pdf", "resolved_path": "b.pdf", "raw_text": "b.pdf"},
            {"original_link": "c.pdf", "resolved_path": "c.pdf", "raw_text": "c.pdf"},
        ]

        class DummyExecutor:
            last_max_workers = None

            def __init__(self, max_workers):
                DummyExecutor.last_max_workers = max_workers
                self.futures = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, link):
                future = MagicMock()
                future.result.return_value = {
                    "file_path": link["resolved_path"],
                    "original_link": link["original_link"],
                    "raw_text": link["raw_text"],
                    "exists": True,
                    "readable": True,
                    "status": "PASS",
                    "error": None,
                }
                self.futures.append(future)
                return future

        fake_futures = types.ModuleType("concurrent.futures")
        fake_futures.ThreadPoolExecutor = DummyExecutor
        fake_futures.as_completed = lambda futures: futures

        fake_concurrent = types.ModuleType("concurrent")
        fake_concurrent.__path__ = []
        fake_concurrent.futures = fake_futures

        original_concurrent = sys.modules.get("concurrent")
        original_concurrent_futures = sys.modules.get("concurrent.futures")
        sys.modules["concurrent"] = fake_concurrent
        sys.modules["concurrent.futures"] = fake_futures

        with patch("os.cpu_count", return_value=2):
            with patch("agents.pdf_validator.PDFValidator", new=MagicMock):
                try:
                    validate_pdfs(state)
                finally:
                    if original_concurrent is None:
                        del sys.modules["concurrent"]
                    else:
                        sys.modules["concurrent"] = original_concurrent
                    if original_concurrent_futures is None:
                        del sys.modules["concurrent.futures"]
                    else:
                        sys.modules["concurrent.futures"] = original_concurrent_futures

        self.assertEqual(DummyExecutor.last_max_workers, 3)

    def test_validate_excel_resolves_explicit_path(self):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp_file:
            excel_path = tmp_file.name

        try:
            state = ReleaseState(pdf_path="C:/tmp/fake.pdf")
            state.excel_path = excel_path

            class FakeValidator:
                def validate(self, pdf_path, excel_path_arg, matching_block, app_name_hint=None):
                    return {"application": "FakeApp", "overall_status": "PASS"}

            with patch("agents.validators.jira_excel_validator.JiraExcelValidator", return_value=FakeValidator()):
                result = validate_excel(state)

            self.assertEqual(result["excel_validation"]["overall_status"], "PASS")
        finally:
            os.remove(excel_path)

    def test_validate_returns_clear_error_when_excel_path_is_missing(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()
        result = validator.validate(
            pdf_path="C:/tmp/OpenGrid 2.3.15.0 Asset Manager Release Notes.pdf",
            excel_path=None,
        )

        self.assertIn("Excel file path was not provided", result["error"])

    def test_compare_reports_unmatched_pdf_rows_as_missing_in_excel(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()
        excel_records = [
            {
                "application": "Asset Manager",
                "account_name": "Account A",
                "client_tracking_number": "CTN-1",
                "ssc_id": "SSC-1",
                "description": "Description 1",
                "functional_model": "Model 1",
            }
        ]
        pdf_records = [
            {
                "Account Name": "Account A",
                "Client Tracking": "CTN-1",
                "SSC ID": "SSC-1",
                "Issue Description": "Description 1",
                "Functional Model": "Model 1",
            },
            {
                "Account Name": "Account A",
                "Client Tracking": "CTN-1",
                "SSC ID": "SSC-1",
                "Issue Description": "Description 2",
                "Functional Model": "Model 2",
            }
        ]

        comparison = validator.compare(excel_records, pdf_records, "Asset Manager")

        self.assertEqual(len(comparison), 2)
        self.assertEqual(comparison[0]["Status"], "PASS")
        self.assertEqual(comparison[1]["Status"], "Missing in Excel")
        self.assertEqual(comparison[1]["Account Name (PDF)"], "Account A")

    def test_format_report_shows_excel_and_pdf_values_for_mismatches(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()
        comparison = [
            {
                "Application Name": "Asset Manager",
                "Account Name (Excel)": "Account A",
                "Account Name (PDF)": "Account B",
                "Client Tracking Number (Excel)": "CTN-1",
                "Client Tracking Number (PDF)": "CTN-1",
                "SSC ID (Excel)": "SSC-1",
                "SSC ID (PDF)": "SSC-1",
                "Issue Description (Excel)": "Description 1",
                "Issue Description (PDF)": "Description 1",
                "Functional Model (Excel)": "Model 1",
                "Functional Model (PDF)": "Model 1",
                "Status": "FAIL",
                "Remarks": "Account Name mismatch (Excel: 'Account A' vs PDF: 'Account B')"
            }
        ]
        report = validator.format_report({
            "application": "Asset Manager",
            "comparison": comparison,
            "total_excel_records": 1,
            "total_pdf_records": 1,
            "matched_records": 0,
            "failed_records": 1,
            "missing_in_pdf": 0,
            "missing_in_excel": 0,
            "overall_status": "FAIL"
        }, latest_version="1.0.0.0")

        self.assertIn("#### Full Comparison Table", report)
        self.assertIn("#### Mismatched Details", report)
        self.assertIn("<td>Account A</td>", report)
        self.assertIn("<td>Account B</td>", report)

    def test_format_report_includes_missing_rows_in_difference_details(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()
        comparison = [
            {
                "Application Name": "Asset Manager",
                "Account Name (Excel)": "Account A",
                "Account Name (PDF)": "",
                "Client Tracking Number (Excel)": "CTN-1",
                "Client Tracking Number (PDF)": "",
                "SSC ID (Excel)": "SSC-1",
                "SSC ID (PDF)": "",
                "Issue Description (Excel)": "Description 1",
                "Issue Description (PDF)": "",
                "Functional Model (Excel)": "Model 1",
                "Functional Model (PDF)": "",
                "Status": "Missing in PDF",
                "Remarks": "Missing in PDF"
            }
        ]

        report = validator.format_report({
            "application": "Asset Manager",
            "comparison": comparison,
            "total_excel_records": 1,
            "total_pdf_records": 0,
            "matched_records": 0,
            "failed_records": 0,
            "missing_in_pdf": 1,
            "missing_in_excel": 0,
            "overall_status": "FAIL"
        }, latest_version="1.0.0.0")

        self.assertIn("#### Full Comparison Table", report)
        self.assertIn("#### Mismatched Details", report)
        self.assertIn("<table>", report)
        self.assertIn("<td>SSC-1</td>", report)
        self.assertIn("<td>Missing in PDF</td>", report)

    def test_validate_scopes_excel_rows_to_matching_block(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()

        excel_records = [
            {
                "application": "Asset Manager",
                "account_name": "Account A",
                "client_tracking_number": "CTN-1",
                "ssc_id": "MNOSD-1001",
                "description": "Desc 1",
                "functional_model": "Model 1",
            },
            {
                "application": "Asset Manager",
                "account_name": "Account B",
                "client_tracking_number": "CTN-2",
                "ssc_id": "MNOSD-9999",
                "description": "Old ticket",
                "functional_model": "Model 2",
            },
        ]

        pdf_records = [
            {
                "Account Name": "Account A",
                "Client Tracking": "CTN-1",
                "SSC ID": "MNOSD-1001",
                "Issue Description": "Desc 1",
                "Functional Model": "Model 1",
            }
        ]

        with patch.object(JiraExcelValidator, "read_excel", return_value=excel_records), \
             patch.object(JiraExcelValidator, "extract_pdf_table", return_value=pdf_records), \
             patch("os.path.exists", return_value=True):
            result = validator.validate(
                pdf_path="C:/tmp/OpenGrid 2.3.15.0[0] Asset Manager Release Notes.pdf",
                excel_path="C:/tmp/jira.xlsx",
                matching_block=["MNOSD-1001"],
            )

        self.assertEqual(result["total_excel_records"], 1)
        self.assertEqual(result["missing_in_pdf"], 0)
        self.assertEqual(result["overall_status"], "PASS")

    def test_compare_matches_pdf_ticket_suffix_artifacts(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()
        excel_records = [
            {
                "application": "Asset Manager",
                "account_name": "Account A",
                "client_tracking_number": "",
                "ssc_id": "MNOSD-28592",
                "description": "Description 1",
                "functional_model": "Model 1",
            }
        ]
        pdf_records = [
            {
                "Account Name": "Account A",
                "Client Tracking": "",
                "SSC ID": "MNOSD-28592BUG",
                "Issue Description": "Description 1",
                "Functional Model": "Model 1",
            }
        ]

        comparison = validator.compare(excel_records, pdf_records, "Asset Manager")

        self.assertEqual(len(comparison), 1)
        self.assertEqual(comparison[0]["Status"], "PASS")

    def test_validate_scopes_rows_using_ticket_ids_in_description(self):
        from agents.validators.jira_excel_validator import JiraExcelValidator

        validator = JiraExcelValidator()

        excel_records = [
            {
                "application": "Asset Manager",
                "account_name": "Account A",
                "client_tracking_number": "",
                "ssc_id": "",
                "description": "Contains ticket MNOSD-40001 in description",
                "functional_model": "Model 1",
            }
        ]

        pdf_records = [
            {
                "Account Name": "Account A",
                "Client Tracking": "",
                "SSC ID": "MNOSD-40001",
                "Issue Description": "Contains ticket MNOSD-40001 in description",
                "Functional Model": "Model 1",
            }
        ]

        with patch.object(JiraExcelValidator, "read_excel", return_value=excel_records), \
             patch.object(JiraExcelValidator, "extract_pdf_table", return_value=pdf_records), \
             patch("os.path.exists", return_value=True):
            result = validator.validate(
                pdf_path="C:/tmp/OpenGrid 2.3.15.0[0] Asset Manager Release Notes.pdf",
                excel_path="C:/tmp/jira.xlsx",
                matching_block=["MNOSD-40001"],
            )

        self.assertEqual(result["total_excel_records"], 1)
        self.assertEqual(result["total_pdf_records"], 1)
        self.assertEqual(result["overall_status"], "PASS")


class TOCValidatorTests(unittest.TestCase):
    def test_heading_on_page_allows_non_contiguous_tokens(self):
        validator = TOCValidator()
        heading = "Application Release Notes"
        page_text = "Release\nfor Application\nNotes section"
        self.assertTrue(validator._heading_on_page(page_text, heading))


class PDFValidatorTests(unittest.TestCase):
    def test_validate_http_error_sets_exists_false_and_http_status(self):
        validator = PDFValidator()
        mock_response = MagicMock()
        mock_response.status_code = 404
        validator.session.head = MagicMock(return_value=mock_response)

        results = validator.validate(["http://example.com/missing.pdf"])

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertFalse(result["exists"])
        self.assertFalse(result["readable"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["error"], "HTTP Error 404")
        self.assertEqual(result["http_status"], 404)

    def test_validate_local_pdf_file_passes(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_pdf_path = tmp_file.name

        try:
            doc = fitz.open()
            doc.new_page()
            doc.save(tmp_pdf_path)
            doc.close()

            validator = PDFValidator()
            results = validator.validate([tmp_pdf_path])

            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertTrue(result["exists"])
            self.assertTrue(result["readable"])
            self.assertEqual(result["status"], "PASS")
            self.assertIsNone(result["error"])
            self.assertIsNone(result["http_status"])
        finally:
            os.remove(tmp_pdf_path)


class VersionValidatorTests(unittest.TestCase):
    def test_validate_picks_highest_numeric_version(self):
        result = VersionValidator().validate("Builds 2.3.10.10 and 2.3.10.2")

        self.assertEqual(result["latest_version"], "2.3.10.10")
        self.assertIn("Version mismatch across document", result["issues"])
        self.assertIn("Build order inconsistency detected", result["issues"])


if __name__ == "__main__":
    unittest.main()