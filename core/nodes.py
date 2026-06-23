import re
from services.pdf_service import PDFService
from agents.pdf_link_extractor import PDFLinkExtractor
from agents.pdf_validator import PDFValidator
from agents.validators.toc_validator import TOCValidator
from utils.path_resolver import PathResolver
from utils.version_utils import extract_version_from_path, extract_version_from_change_summary, normalize_version

from services.report_service import ReportService
from core.state import ReleaseState


def sanitize_path(path_str: str) -> str:
    """Removes null bytes and non-printable control characters from paths."""
    if not path_str:
        return ""
    # Remove null bytes and ASCII control characters (0-31 and 127)
    # We preserve normal text and valid unicode characters.
    cleaned = re.sub(r'[\x00-\x1F\x7F]', '', str(path_str))
    # Strip whitespace and any stray enclosing quotes from PDF extraction
    return cleaned.strip().strip('"\'').strip()

def extract_pdf(state: ReleaseState):
    print("Extracting PDF text...")
    pdf = PDFService()
    state.text = pdf.extract_text(state.pdf_path)

    # Prefer the version from the change summary last row over the filename.
    # The change summary last row is the authoritative latest release version.
    cs_version = extract_version_from_change_summary(state.text)
    if cs_version:
        state.system_determined_latest_version = cs_version
    elif (
        not getattr(state, "system_determined_latest_version", "")
        or state.system_determined_latest_version == "Unknown"
    ):
        # Extract bracket version directly from path to prevent loss of bracket notation
        path_match = re.search(r'(\d+(?:\.\d+)+(?:\[\d+\])?)', state.pdf_path)
        if path_match:
            state.system_determined_latest_version = path_match.group(1)
        else:
            state.system_determined_latest_version = extract_version_from_path(state.pdf_path)

        # Fallback: Extract version from the first page of the PDF text if filename fails
        if not state.system_determined_latest_version or state.system_determined_latest_version == "Unknown":
            fallback_match = re.search(r'(?:Version|Release|Build)\s*[:\-]?\s*(\d+(?:\.\d+)+(?:\[\d+\])?)', state.text[:1500], re.IGNORECASE)
            if fallback_match:
                state.system_determined_latest_version = fallback_match.group(1)

    return {
        "text": state.text,
        "system_determined_latest_version": state.system_determined_latest_version,
    }


def extract_links(state: ReleaseState):
    print("Extracting PDF links...")
    extractor = PDFLinkExtractor()
    state.raw_links = extractor.extract_links(state.pdf_path)
    return {"raw_links": state.raw_links}


def resolve_paths(state: ReleaseState):
    print("Resolving file paths...")
    resolver = PathResolver()
    resolved = []
    seen = set()
    for link in state.raw_links:
        clean_link = sanitize_path(link.get("link", ""))
        resolved_path = sanitize_path(resolver.resolve(state.pdf_path, clean_link))
        if resolved_path not in seen:
            seen.add(resolved_path)
            resolved.append(resolved_path)
    state.resolved_paths = resolved
    return {"resolved_paths": state.resolved_paths}


def validate_pdfs(state: ReleaseState):
    print("Validating linked PDFs...")
    from agents.pdf_validator import PDFValidator
    import concurrent.futures

    results = []
    
    path_mapping = {}
    resolver = PathResolver()
    for link in state.raw_links:
        clean_link = sanitize_path(link.get("link", ""))
        resolved_path = sanitize_path(resolver.resolve(state.pdf_path, clean_link))
        path_mapping[resolved_path] = clean_link

    def check_pdf(raw_path):
        validator = PDFValidator()
        path = sanitize_path(raw_path)
        print(f"Checking file: {repr(path)}")
        res = validator.validate([path])[0]
        res["original_link"] = path_mapping.get(path, path)
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        results = list(executor.map(check_pdf, state.resolved_paths))

    state.pdf_validation = results
    return {"pdf_validation": state.pdf_validation}


def validate_toc(state: ReleaseState):
    print("Validating table of contents navigation...")
    validator = TOCValidator()
    latest_version = getattr(state, "system_determined_latest_version", None)
    state.toc_validation = validator.validate(state.pdf_path, latest_version)
    return {"toc_validation": state.toc_validation}


def generate_report(state: ReleaseState):
    print("Generating Final AI Report via Master Prompt...")
    report = ReportService()
    
    # Passing state as a dict since that is what ReportService currently expects
    state_dict = {
        "pdf_path": state.pdf_path,
        "text": state.text,
        "pdf_validation": state.pdf_validation,
        "toc_validation": state.toc_validation,
        "system_determined_latest_version": getattr(state, "system_determined_latest_version", "Unknown")
    }
    
    report_text, report_path = report.generate(state_dict)
    state.report_path = report_path
    state.final_report = report_text
    print(f"Report successfully saved to: {report_path}")
    
    return {"final_report": state.final_report, "report_path": state.report_path}
