import re
import os
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
    
    # Strip Windows hidden directional characters (e.g. from "Copy as path")
    cleaned = cleaned.strip('\u202a\u202b\u202c\u202d\u202e')
    
    # Strip URL query parameters (?) and fragments (#) which cause OSError 22 on Windows
    if '?' in cleaned:
        cleaned = cleaned.split('?')[0]
    if '#' in cleaned:
        cleaned = cleaned.split('#')[0]
        
    # Remove invalid Windows file path characters (excluding : \ / which are valid separators)
    cleaned = re.sub(r'[<>|"*\x00]', '', cleaned)
    
    # Strip whitespace and any stray enclosing quotes from PDF extraction
    return cleaned.strip().strip('"\'').strip()

def safe_exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except OSError:
        return False

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
    resolved_links = []
    seen_paths = set()
    import urllib.parse
    base_dir = os.path.dirname(os.path.abspath(state.pdf_path))
    
    for link_obj in state.raw_links:
        original_link = sanitize_path(link_obj.get("link", ""))
        raw_text = link_obj.get("raw_text", original_link) # Get raw text, fallback to original link
        unquoted_link = urllib.parse.unquote(urllib.parse.unquote(original_link))
        resolved_path = sanitize_path(resolver.resolve(state.pdf_path, unquoted_link))
        
        if resolved_path.startswith("file:///"):
            resolved_path = resolved_path[8:]
        elif resolved_path.startswith("file://"):
            resolved_path = resolved_path[7:]
        elif resolved_path.startswith("file:/"):
            resolved_path = resolved_path[6:]
        if os.name == 'nt' and resolved_path.startswith('/') and len(resolved_path) > 2 and resolved_path[2] == ':':
            resolved_path = resolved_path[1:]
            
        if not os.path.isabs(resolved_path) and not resolved_path.lower().startswith(('http://', 'https://')):
            resolved_path = os.path.normpath(os.path.join(base_dir, resolved_path))
            
        if os.path.isabs(resolved_path) and not safe_exists(resolved_path):
            parts = [p for p in resolved_path.replace('\\', '/').split('/') if p and not p.endswith(':')]
            for i in range(len(parts)):
                fallback = os.path.normpath(os.path.join(base_dir, *parts[i:]))
                if safe_exists(fallback):
                    resolved_path = fallback
                    break
            else:
                filename = os.path.basename(resolved_path)
                fallback = os.path.normpath(os.path.join(base_dir, filename))
                if safe_exists(fallback):
                    resolved_path = fallback
                else:
                    # Broaden search to parent directories for sibling folder links (e.g., extracted zip packages)
                    search_dir = base_dir
                    for _ in range(3):
                        parent = os.path.dirname(search_dir)
                        # Safeguard: prevent walking the entire C:\ or User root directory to avoid slow performance
                        if parent == search_dir or len(parent.split(os.sep)) <= 3:
                            break
                        search_dir = parent

                    found = False
                    for root_dir, dirs, files in os.walk(search_dir):
                        dirs[:] = [d for d in dirs if d.lower() != 'common']
                        if filename in files:
                            resolved_path = os.path.normpath(os.path.join(root_dir, filename))
                            found = True
                            break
                    if not found:
                        lower_filename = filename.lower()
                        for root_dir, dirs, files in os.walk(search_dir):
                            dirs[:] = [d for d in dirs if d.lower() != 'common']
                            file_map = {f.lower(): f for f in files}
                            if lower_filename in file_map:
                                resolved_path = os.path.normpath(os.path.join(root_dir, file_map[lower_filename]))
                                break

        norm_resolved_path = resolved_path.lower()
        if norm_resolved_path not in seen_paths:
            seen_paths.add(norm_resolved_path)
            resolved_links.append({
                "original_link": original_link,
                "raw_text": link_obj.get("raw_text", original_link),
                "resolved_path": resolved_path
            })
            
    state.resolved_links = resolved_links
    return {"resolved_links": state.resolved_links}


def validate_pdfs(state: ReleaseState):
    print("Validating linked PDFs...")
    from agents.pdf_validator import PDFValidator
    import concurrent.futures

    def check_pdf(link_info: dict):
        validator = PDFValidator()
        path = link_info["resolved_path"]
        res = validator.validate([path])[0]
        res["original_link"] = link_info["original_link"]
        res["raw_text"] = link_info.get("raw_text", link_info["original_link"])
        return res

    num_links = max(1, len(state.resolved_links))
    cpu_count = (os.cpu_count() or 1)
    # Adaptive worker count: cap to avoid runaway threads but allow some parallelism for I/O
    max_workers = min(32, max(1, cpu_count * 5), num_links)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_link = {executor.submit(check_pdf, link): link for link in state.resolved_links}
        for fut in concurrent.futures.as_completed(future_to_link):
            link_info = future_to_link[fut]
            try:
                res = fut.result()
                results.append(res)
            except Exception as e:
                # Log and continue with a structured failure result for this link
                print(f"Warning: validation failed for {link_info.get('resolved_path')}: {e}", flush=True)
                results.append({
                    "file_path": link_info.get("resolved_path"),
                    "original_link": link_info.get("original_link"),
                    "raw_text": link_info.get("raw_text", link_info.get("original_link")),
                    "exists": False,
                    "readable": False,
                    "status": "FAIL",
                    "error": f"Exception during validation: {e}"
                })

    state.pdf_validation = results
    return {"pdf_validation": state.pdf_validation}


def validate_toc(state: ReleaseState):
    print("Validating table of contents navigation...")
    validator = TOCValidator()
    latest_version = getattr(state, "system_determined_latest_version", None)
    state.toc_validation = validator.validate(state.pdf_path, latest_version)
    return {"toc_validation": state.toc_validation}


def validate_excel(state: ReleaseState):
    print("Validating Excel against PDF...")
    from agents.validators.jira_excel_validator import JiraExcelValidator
    
    def resolve_excel_path(path_value: str) -> str:
        if not path_value:
            return ""
        path_value = sanitize_path(path_value)
        candidates = [path_value]
        if not os.path.isabs(path_value):
            base_dir = os.path.dirname(os.path.abspath(state.pdf_path))
            candidates.append(os.path.abspath(os.path.join(base_dir, path_value)))
        candidates.append(os.path.expandvars(path_value))
        candidates.append(os.path.expanduser(path_value))
        if os.path.sep == "\\":
            candidates.append(path_value.replace("/", "\\"))
            candidates.append(os.path.expandvars(path_value.replace("/", "\\")))
            candidates.append(os.path.expanduser(path_value.replace("/", "\\")))

        for candidate in candidates:
            candidate = sanitize_path(candidate)
            if candidate and safe_exists(candidate):
                return candidate

        return sanitize_path(path_value)

    excel_path = resolve_excel_path(getattr(state, "excel_path", "") or os.environ.get("APP_EXCEL_PATH", ""))
    print(f"Resolved Excel path: '{excel_path}', exists={safe_exists(excel_path)}")

    if excel_path and safe_exists(excel_path):
        report_service = ReportService()
        build_blocks = report_service.extract_build_blocks(state.text)
        latest_version = getattr(state, "system_determined_latest_version", "Unknown")
        _, selected_block = report_service._select_relevant_build_block(build_blocks, latest_version)
        matching_block = selected_block.get("tickets", []) if selected_block else []
        
        validator = JiraExcelValidator()
        pdf_filename = os.path.basename(state.pdf_path)
        result = validator.validate(state.pdf_path, excel_path, matching_block, app_name_hint=pdf_filename)
        if result is None:
            state.excel_validation = {"error": f"Failed to validate Excel. Invalid path: {excel_path}"}
        else:
            state.excel_validation = result
    else:
        state.excel_validation = {"error": f"Excel file not found or path not provided: '{excel_path}'"}
        
    return {"excel_validation": state.excel_validation}


def generate_report(state: ReleaseState):
    print("Generating Final AI Report via Master Prompt...")
    
    excel_path = getattr(state, "excel_path", "")
    if not excel_path:
        excel_path = os.environ.get("APP_EXCEL_PATH", "")

    report = ReportService()
    
    # Passing state as a dict since that is what ReportService currently expects
    state_dict = {
        "pdf_path": state.pdf_path,
        "excel_path": excel_path,
        "text": state.text,
        "pdf_validation": getattr(state, "pdf_validation", []),
        "toc_validation": getattr(state, "toc_validation", {}),
        "excel_validation": getattr(state, "excel_validation", {}),
        "system_determined_latest_version": getattr(state, "system_determined_latest_version", "Unknown")
    }
    
    pdf_filename = os.path.basename(state.pdf_path)
    report_filename = f"validation_report_{os.path.splitext(pdf_filename)[0]}.txt"
    report_out_path = os.path.join("reports", report_filename)
    
    report_text, report_path = report.generate(state_dict, output_path=report_out_path)
    state.report_path = report_path
    state.final_report = report_text
    print(f"Report successfully saved to: {report_path}")
    
    return {"final_report": state.final_report, "report_path": state.report_path}
