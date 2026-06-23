import re

class JiraValidator:
    def __init__(self):
        pass

    def validate_latest_release_tickets(self, text: str, latest_version: str):

        result = {
            "latest_version": latest_version,
            "tickets": [],
            "issues": []
        }

        # EXTRA SAFETY (CRITICAL)
        if not latest_version:
            result["issues"].append("latest_version is None or empty")
            return result

        # Look specifically in Appendix A or B for the latest version
        # Assuming the structure mentions the version in Appendix A/B (e.g. "Build Number: ARM <version>")
        pattern = (
            rf"Appendix\s+[AB].*?Build Number: ARM {re.escape(str(latest_version))}"
            rf"(.*?)(Appendix\s+[A-Z]|Build Number:|$)"
        )

        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if not match:
            # Fallback to general search if Appendix A/B with version is not explicitly matched
            pattern = rf"Appendix\s+[AB](.*?)(Appendix\s+[C-Z]|Build Number:|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            
            if not match:
                result["issues"].append("Latest version section or Appendix A/B not found")
                return result

        section = match.group(1)

        tickets = set(
            re.findall(r"(WAMAT-\d+|MNOSD-\d+)", section)
        )

        for t in tickets:
            result["tickets"].append({
                "ticket": t,
                "present_in_pdf": True
            })

        return result
