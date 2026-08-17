import re
from datetime import datetime

class DateValidator:

    DATE_PATTERNS = [
        re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
        re.compile(r"\b\d{2}-\d{2}-\d{4}\b"),
        re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
        re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"),
        re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b"),
        re.compile(r"\b[A-Za-z]{3,9}-\d{1,2}-\d{4}\b"),
    ]

    DATE_FORMATS = [
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b-%d-%Y",
        "%B-%d-%Y",
    ]

    def _parse_date(self, date_str: str):
        for fmt in self.DATE_FORMATS:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    def _extract_date_candidates(self, text: str):
        if not text:
            return []

        candidates = []
        seen = set()
        for pattern in self.DATE_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0).strip()
                key = (match.start(), value)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append((match.start(), value))

        candidates.sort(key=lambda item: item[0])
        return [value for _, value in candidates]

    def validate(self, text):
        expected_date_obj = datetime.today().date()
        expected_date = expected_date_obj.strftime("%m-%d-%Y")

        release_date = None
        parsed_release_date = None
        for candidate in self._extract_date_candidates(text):
            parsed = self._parse_date(candidate)
            if parsed:
                release_date = candidate
                parsed_release_date = parsed
                break

        if not parsed_release_date:
            status = "NOT_FOUND"
            relation = "unknown"
            normalized_found_date = "Not Found"
        elif parsed_release_date == expected_date_obj:
            status = "VALID"
            relation = "current"
            normalized_found_date = parsed_release_date.strftime("%m-%d-%Y")
        elif parsed_release_date < expected_date_obj:
            status = "PAST"
            relation = "previous"
            normalized_found_date = parsed_release_date.strftime("%m-%d-%Y")
        else:
            status = "FUTURE"
            relation = "future"
            normalized_found_date = parsed_release_date.strftime("%m-%d-%Y")

        return {
            "release_date": release_date,
            "normalized_release_date": normalized_found_date,
            "system_date": expected_date,
            "status": status,
            "relation": relation,
        }