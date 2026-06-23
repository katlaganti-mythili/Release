import re


def extract_version_from_change_summary(text: str) -> str:
    """
    Extract the latest version from the last 'Build Number' row in the
    Change Summary / Appendix section.  The document lists versions from
    oldest to newest, so the LAST match is the most recent release.
    Returns empty string when nothing is found.
    """
    if not text:
        return ""
        
    appendix_pattern = re.compile(r'(Appendix\s+[AB].*?)(?=Appendix\s+[C-Z]|$)', re.DOTALL | re.IGNORECASE)
    appendices = appendix_pattern.findall(text)
    search_text = " ".join(appendices) if appendices else text

    matches = re.findall(
        r"Build\s+Number[:\s]*(?:.{0,150}?)(?<!\d)(\d+(?:\.\d+)+(?:\[\d+\])?(?:[\s\-]*Patch\s*\d+)?(?:[\s\-]*Hotfix\s*\d+)?)",
        search_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not matches:
        return ""
    return sorted(matches, key=version_sort_key)[-1].strip()


def extract_version_from_path(path: str) -> str:
    if not path:
        return "Unknown"

    match = re.search(r"\d+(?:\.\d+)+", path)
    return match.group(0) if match else "Unknown"


def normalize_version(version: str) -> str:
    if not version:
        return ""

    version = version.strip()
    version = re.sub(r"\[(\d+)\]", r".\1", version)
    return version


def version_sort_key(version: str) -> tuple[int, ...]:
    normalized = normalize_version(version)
    if not normalized:
        return tuple()

    return tuple(int(part) for part in re.findall(r'\d+', normalized))


def compare_versions(v1: str, v2: str) -> bool:
    return normalize_version(v1) == normalize_version(v2)