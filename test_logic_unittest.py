import unittest

from agents.version_validator import VersionValidator
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
            {"ticket_exists": lambda self, ticket: True},
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

        service.generate(
            {
                "pdf_path": "C:/tmp/OpenGrid 2.0.0.0 Product Release Notes.pdf",
                "text": text,
                "pdf_validation": [],
                "system_determined_latest_version": "2.0.0.0",
            },
            output_path="reports/_tmp_validation.txt",
        )

        prompt = captured["prompt"]
        self.assertIn("Found date: 06-21-2026", prompt)
        self.assertIn("- jira ticket found (2.0.0.0): MNOSD-2 [Verified in Jira]", prompt)
        self.assertIn("- **Release Type:** HOTFIX", prompt)


class VersionValidatorTests(unittest.TestCase):
    def test_validate_picks_highest_numeric_version(self):
        result = VersionValidator().validate("Builds 2.3.10.10 and 2.3.10.2")

        self.assertEqual(result["latest_version"], "2.3.10.10")
        self.assertIn("Version mismatch across document", result["issues"])
        self.assertIn("Build order inconsistency detected", result["issues"])


if __name__ == "__main__":
    unittest.main()