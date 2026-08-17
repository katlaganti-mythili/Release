import re
from utils.version_utils import normalize_version, version_sort_key


class VersionValidator:

    def validate(self, text: str):

        result = {
            "latest_version": None,
            "all_versions": [],
            "issues": []
        }

        if not text:
            result["issues"].append("Empty PDF text")
            return result

        versions = re.findall(
            r"\d+\.\d+\.\d+\.\d+(?:\[\d+\])?",
            text
        )

        if not versions:
            result["issues"].append("No version found in document")
            result["latest_version"] = "UNKNOWN"
            return result

        normalized = [normalize_version(v) for v in versions]
        version_keys = [version_sort_key(v) for v in normalized]

        result["all_versions"] = normalized
        result["latest_version"] = max(normalized, key=version_sort_key)

        # INTELLIGENCE RULES
        if len(set(normalized)) > 1:
            result["issues"].append("Version mismatch across document")

        if version_keys != sorted(version_keys):
            result["issues"].append("Build order inconsistency detected")

        return result