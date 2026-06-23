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

        norm_version = re.sub(r"\[(\d+)\]", r".\1", str(latest_version))
        base_match = re.search(r"(\d+(?:\.\d+)+(?:\[\d+\])?)", str(latest_version))
        base_version = base_match.group(1) if base_match else str(latest_version)
        
        esc_latest = re.escape(base_version)
        esc_norm = re.escape(norm_version)
        version_pattern = rf"(?:{esc_latest}|{esc_norm})"

        # Look specifically in Appendix A or B for the latest version
        pattern = (
            rf"Appendix\s+[AB].*?Build\s+Number[:\s]*(?:.{{0,150}}?)(?<!\d){version_pattern}"
            rf"(.*?)(Appendix\s+[A-Z]|Build\s+Number:|$)"
        )

        matches = list(re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))
        
        tickets = set()

        if matches:
            for match in matches:
                section = match.group(1)
                found_tickets = re.findall(r"\b([A-Za-z]{2,15}\s*-\s*\d+)\b", section)
                tickets.update(t.upper().replace(' ', '') for t in found_tickets)
        else:
            # Fallback to general search if Appendix A/B with version is not explicitly matched
            pattern = rf"Appendix\s+[AB](.*?)(Appendix\s+[C-Z]|Build\s+Number:|$)"
            matches = list(re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))
            
            if not matches:
                result["issues"].append("Latest version section or Appendix A/B not found")
                return result

            for match in matches:
                section = match.group(1)
                # Ensure the section actually mentions the latest version to avoid grabbing older tickets
                if not re.search(rf"(?<!\d){version_pattern}(?!\d)", section):
                    continue
                found_tickets = re.findall(r"\b([A-Za-z]{2,15}\s*-\s*\d+)\b", section)
                tickets.update(t.upper().replace(' ', '') for t in found_tickets)

        for t in tickets:
            result["tickets"].append({
                "ticket": t,
                "present_in_pdf": True
            })

        return result
