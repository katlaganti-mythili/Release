import json
import os
import re
import urllib.parse
from datetime import datetime
from agents.version_validator import VersionValidator
from agents.validators.date_validator import DateValidator
from services.ollama_service import OllamaService
from services.jira_service import JiraService
from agents.validators.jira_excel_validator import JiraExcelValidator
from agents.validators.jira_validator import JiraValidator
from utils.version_utils import extract_version_from_change_summary

TICKET_ID_PATTERN = re.compile(
    r"(?i)\b((?:MNOSD|WAMAT)\s*[-–—]\s*\d+(?:\s*[-–—]\s*\d+)*(?:[A-Z])?)(?:\s*(?:BUG|SWG))?\b"
)


def normalize_ticket_id(ticket: str) -> str:
    if not ticket:
        return ""
    normalized = re.sub(r"\s+", "", str(ticket)).upper()
    normalized = normalized.replace("–", "-").replace("—", "-")
    return normalized

MASTER_PROMPT = """# Release Validation Report

## 1. File Summary
- **File:** {source_pdf_file_name}
- **Detected Latest Version:** {system_determined_latest_version}
- **Release Type:** {system_determined_release_type}

## 2. Version Validation
- **Latest Version Consistency:** {system_determined_version_consistency}
- **Details:** {system_determined_version_details}

## 3. Release Date Validation
{system_determined_date_validation}

## 4. Jira Tickets (Latest Version)
{system_determined_jira_tickets}

## 5. Table of Contents
{system_determined_toc_validation}"""

class ReportService:
    def __init__(self):
        self.llm = OllamaService()
        self.jira_service = JiraService()
        self.version_validator = VersionValidator()
        self.jira_excel_validator = JiraExcelValidator()
        self.date_validator = DateValidator()

    def _select_relevant_build_block(self, build_blocks: dict, latest_version: str):
        if not build_blocks:
            return None, None

        merged_key = []
        merged_tickets = set()
        merged_content = []

        if latest_version and latest_version != "Unknown":
            base_match = re.search(r"(\d+(?:\.\d+)+(?:\[\d+\])?)", latest_version)
            base_version = base_match.group(1) if base_match else latest_version
            norm_base = re.sub(r"\[(\d+)\]", r".\1", base_version)
            
            def has_ver(v, text_block):
                return bool(re.search(rf'(?<!\d){re.escape(v)}(?!\d)', text_block))
                
            for key, data in build_blocks.items():
                if key == "GLOBAL_APPENDIX_TICKETS":
                    continue
                norm_key = re.sub(r"\[(\d+)\]", r".\1", key)
                block_content = data.get("content", "")
                
                # Strictly match the header to avoid pulling in old releases that merely mention the new version
                if (
                    has_ver(base_version, key)
                    or has_ver(norm_base, norm_key)
                    or has_ver(base_version, block_content)
                    or has_ver(norm_base, block_content)
                ):
                    merged_key.append(key)
                    merged_tickets.update(data.get("tickets", []))
                    merged_content.append(block_content)
                    
            if merged_key:
                global_data = build_blocks.get("GLOBAL_APPENDIX_TICKETS", {})
                global_content = global_data.get("content", "")
                global_tickets = global_data.get("tickets", [])
                if global_tickets and (has_ver(base_version, global_content) or has_ver(norm_base, global_content) or len(build_blocks) <= 2):
                    merged_tickets.update(global_tickets)
                return " & ".join(merged_key), {"tickets": list(merged_tickets), "content": "\n".join(merged_content)}

        last_key = list(build_blocks.keys())[-1]
        if last_key == "GLOBAL_APPENDIX_TICKETS" and len(build_blocks) > 1:
            last_key = list(build_blocks.keys())[-2]
        return last_key, build_blocks[last_key]

    def extract_build_blocks(self, text: str) -> dict:
        results = {}
        # Find Appendices A and B specifically to narrow search
        appendix_pattern = re.compile(r'(Appendix\s+[AB].*?)(?=Appendix\s+[C-Z]|$)', re.DOTALL | re.IGNORECASE)
        appendices = appendix_pattern.findall(text)
        
        search_areas = appendices if appendices else [text]
        global_tickets = set()
        global_content_text = ""
        is_appendix = bool(appendices)
        
        for area in search_areas:
            parts = re.split(r'Build\s+Number[:\s]*', area, flags=re.IGNORECASE)
            
            if is_appendix and parts[0].strip():
                global_content_text += "\n" + parts[0].strip()
                # Extract Jira tickets anywhere in the block.
                # Handles newlines, spaces, and PDF-specific dashes (–, —) between prefix and number.
                found_pre = [normalize_ticket_id(ticket) for ticket in TICKET_ID_PATTERN.findall(parts[0])]
                global_tickets.update(found_pre)
                
            for part in parts[1:]:
                clean_part = part.strip()
                if not clean_part:
                    continue
                
                # Extract header using the version pattern to ensure version is included
                block_version_match = re.search(
                    r'^(.{0,150}?)(?<!\d)(\d+(?:\.\d+)+(?:\[\d+\])?(?:[\s\-]*Patch\s*\d+)?(?:[\s\-]*Hotfix\s*\d+)?)', 
                    clean_part, 
                    re.IGNORECASE | re.DOTALL
                )
                
                if block_version_match:
                    prefix = re.sub(r'\s+', ' ', block_version_match.group(1).strip())
                    version_str = block_version_match.group(2)
                    header = f"{prefix} {version_str}".strip()
                else:
                    lines = clean_part.split('\n')
                    header_lines = []
                    for l in lines[:3]:
                        if l.strip():
                            header_lines.append(l.strip())
                    header = " ".join(header_lines)[:150]
                
                # Look for Jira tickets anywhere in the block.
                # Handles newlines, spaces, and PDF-specific dashes (–, —).
                found_tickets = [normalize_ticket_id(ticket) for ticket in TICKET_ID_PATTERN.findall(clean_part)]
                tickets = found_tickets
                
                if header not in results:
                    results[header] = {"tickets": set(), "content": ""}
                results[header]["tickets"].update(tickets)
                results[header]["content"] += "\n" + clean_part
                
        if global_tickets:
            results["GLOBAL_APPENDIX_TICKETS"] = {"tickets": list(global_tickets), "content": global_content_text}
                
        return {k: {"tickets": list(v["tickets"]), "content": v["content"]} for k, v in results.items()}

    def generate(self, state: dict, output_path="reports/validation_report.txt"):
        
        pdf_path = state.get("pdf_path", "Unknown")
        excel_path = state.get("excel_path", "")
        text = state.get("text", "")
        system_determined_latest_version = state.get("system_determined_latest_version", "Unknown")
        toc_validation = state.get("toc_validation", {})
        
        # Format as MM-DD-YYYY to match what user is seeing in the PDF
        current_date = datetime.today().strftime("%m-%d-%Y")
        
        # Extract Jira tickets grouped by exact Build Number blocks
        build_blocks = self.extract_build_blocks(text)
        
        # Check PDF links status to pass to LLM for final summary calculation
        pdf_checks = state.get("pdf_validation", [])
        # Compute consistent counters up front so summary and details use the same semantics
        total_paths = len(pdf_checks)
        readable_count = sum(1 for p in pdf_checks if p.get("readable") or p.get("status") == "PASS")
        not_found_count = sum(1 for p in pdf_checks if not p.get("exists"))
        unreadable_count = sum(1 for p in pdf_checks if p.get("exists") and not (p.get("readable") or p.get("status") == "PASS"))
        # Missing means either not found or exists-but-unreadable
        pdf_missing = not_found_count + unreadable_count
        pdf_links_status = "FAIL (Contains broken or missing links)" if pdf_missing > 0 else "PASS"
        
        # Determine Version, Date, Jira Tickets, Release Type, and TOC status Deterministically
        # Extract the version strictly from the Change Summary to avoid false positives (e.g. IP addresses)
        latest_text_version = extract_version_from_change_summary(text) or "UNKNOWN"

        if latest_text_version == "UNKNOWN":
            version_consistency = "FAIL"
            version_details = "No versions were found in the document."
        elif latest_text_version == system_determined_latest_version:
            version_consistency = "PASS"
            version_details = f"The latest version found in the document ({latest_text_version}) matches the expected latest version."
        else:
            version_consistency = "FAIL"
            version_details = (
                f"The latest version found in the document ({latest_text_version}) does not match "
                f"the expected latest version ({system_determined_latest_version}). Historical older versions are ignored."
            )

        date_validation_str = ""
        matching_block = []
        latest_block_content = ""

        selected_block_key, selected_block = self._select_relevant_build_block(
            build_blocks,
            system_determined_latest_version,
        )
        if selected_block_key and selected_block:
            latest_block_content = selected_block.get("content", "").lower()
            matching_block = selected_block.get("tickets", [])

        # Primary source: extract SSC IDs strictly from the latest-version section.
        # This avoids pulling IDs from older versions while covering multi-page continuations.
        latest_only_tickets = []
        try:
            jira_latest = JiraValidator().validate_latest_release_tickets(text, system_determined_latest_version)
            latest_only_tickets = [normalize_ticket_id(t.get("ticket", "")) for t in jira_latest.get("tickets", []) if t.get("ticket")]
        except Exception:
            latest_only_tickets = []

        # Fallback to block selection only when latest-section extraction is empty.
        source_tickets = latest_only_tickets if latest_only_tickets else matching_block
        deduped_tickets = []
        seen_tickets = set()
        for t in source_tickets:
            nt = normalize_ticket_id(t)
            if nt and nt not in seen_tickets:
                seen_tickets.add(nt)
                deduped_tickets.append(nt)
        matching_block = deduped_tickets

        # Include intro page text to find the release date mentioned in the summary or intro page
        intro_text = text[:3000] if text else ""
        block_text = f"{selected_block_key or ''}\n{latest_block_content}".strip()

        # Always extract from both to ensure we get the Home Page date even if block date exists
        block_date_result = self.date_validator.validate(block_text)
        intro_date_result = self.date_validator.validate(intro_text[:1500])
            
        if block_date_result.get("status") != "NOT_FOUND":
            date_result = block_date_result
        elif intro_date_result.get("status") != "NOT_FOUND":
            date_result = intro_date_result
        else:
            date_result = block_date_result
            
        date_found = date_result.get("normalized_release_date", "Not Found")
        
        home_date_match = re.search(r'\b([A-Za-z]{3}-\d{1,2}-\d{4})\b', intro_text[:1500], re.IGNORECASE)
        if home_date_match:
            parts = home_date_match.group(1).split('-')
            raw_date = f"{parts[0].capitalize()}-{parts[1]}-{parts[2]}"
        else:
            raw_date = intro_date_result.get("release_date", "Not Found")
            
        relation = date_result.get("relation", "unknown")
        date_status = date_result.get("status", "NOT_FOUND")

        path_lower = pdf_path.lower()
        intro_text_lower = intro_text.lower()

        if ('hf' in path_lower or 'hotfix' in path_lower or 
            'hf' in latest_block_content or 'hotfix' in latest_block_content or 
            'hotfix' in intro_text_lower):
            release_type = "HOTFIX"
        elif (re.search(r'\bp\d+\b', path_lower) or 'patch' in path_lower or 
              re.search(r'\bp\d+\b', latest_block_content) or 'patch' in latest_block_content or 
              'patch' in intro_text_lower):
            release_type = "PATCH"
        else:
            release_type = "MINOR/MAJOR"

        date_msg = f"Found date: {date_found} (Home Page date found: {raw_date})" if raw_date and raw_date != "Not Found" else f"Found date: {date_found}"

        if date_status == "VALID":
            date_validation_str = f"- **Status:** VALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date matches the expected date."
        elif date_status == "PAST":
            date_validation_str = f"- **Status:** INVALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date is a previous date ({relation})."
        elif date_status == "FUTURE":
            date_validation_str = f"- **Status:** INVALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date is a future date ({relation})."
        else:
            date_validation_str = f"- **Status:** INVALID\n- **Result:** Found date: Not Found, expected date: {current_date}\n- **Details:** No parseable release date was found in the document block."

        if toc_validation and toc_validation.get("entries"):
            entries = toc_validation["entries"]
            toc_source = toc_validation.get("toc_source", "")
            source_note = f" ({toc_source} TOC)" if toc_source else ""
            toc_validation_str = (
                f"- **TOC Structure:** {toc_validation.get('toc_structure', 'INVALID')}{source_note}\n"
                f"- **Navigation Correctness:** {toc_validation.get('navigation_correctness', 'FAIL')}\n"
                f"- **Details:** {toc_validation.get('details', '')}\n\n"
                "**Per-Section Version & Date Validation:**\n\n"
                f"| Section | Page | Navigation | Latest Version ({system_determined_latest_version}) | Date(s) Found |\n"
                "|---------|------|------------|------------------------------------------------------|---------------|\n"
            )
            for e in entries:
                nav = e.get("status", "FAIL")
                vers = e.get("versions_found", [])
                dates = e.get("dates_found", [])
                
                # Check if latest version appears in this section
                latest_present = system_determined_latest_version in vers
                if not latest_present:
                    base_sys_match = re.search(r"(\d+(?:\.\d+)+(?:\[\d+\])?)", system_determined_latest_version)
                    if base_sys_match:
                        base_sys = base_sys_match.group(1)
                        latest_present = any(base_sys in v for v in vers)

                latest_cell = "Present" if latest_present else "Not found"
                # Show first 3 dates (trim older historical ones if too many)
                dates_cell = ", ".join(dates[:3]) if dates else "-"
                toc_validation_str += f"| {e.get('heading', 'Unknown')} | {e.get('page', '-')} | {nav} | {latest_cell} | {dates_cell} |\n"

        elif toc_validation:
            toc_source = toc_validation.get("toc_source", "")
            source_note = f" ({toc_source} TOC)" if toc_source else ""
            toc_validation_str = (
                f"- **TOC Structure:** {toc_validation.get('toc_structure', 'INVALID')}{source_note}\n"
                f"- **Navigation Correctness:** {toc_validation.get('navigation_correctness', 'FAIL')}\n"
                f"- **Details:** {toc_validation.get('details', 'TOC validation details unavailable.')}"
            )
        else:
            toc_validation_str = (
                "- **TOC Structure:** INVALID\n"
                "- **Navigation Correctness:** FAIL\n"
                "- **Details:** TOC validation was not performed."
            )

        if matching_block:
            jira_lines = []
            print(f"Found {len(matching_block)} extracted SSC IDs in the PDF. Skipping live Jira API validation...")
            
            for t in matching_block:
                jira_lines.append(f"- SSC ID found ({system_determined_latest_version}): {t} [found in pdf]")
                
            jira_tickets_str = "\n".join(jira_lines)
        else:
            jira_tickets_str = "SSC IDs not found in latest version section of PDF"

        jira_tickets_str = f"**Extracted SSC IDs (Latest Version from PDF):**\n{jira_tickets_str}"

        # Run Excel-vs-PDF Jira comparison inline under Jira validation (no separate validation stage).
        excel_path_used = state.get("excel_path") or os.environ.get("APP_EXCEL_PATH", "")
        excel_val_results = state.get("excel_validation")

        # If excel_validation was not provided by the node but excel_path_used exists, fallback to calculate
        if not excel_val_results and excel_path_used:
            if not os.path.isabs(excel_path_used) and pdf_path and pdf_path != "Unknown":
                base_dir = os.path.dirname(os.path.abspath(pdf_path))
                excel_path_used = os.path.normpath(os.path.join(base_dir, excel_path_used))

            if os.path.exists(excel_path_used):
                excel_val_results = self.jira_excel_validator.validate(
                    pdf_path,
                    excel_path_used,
                    matching_block=matching_block,
                    app_name_hint=os.path.basename(pdf_path),
                )

        if excel_val_results and "error" not in excel_val_results:
            excel_report = self.jira_excel_validator.format_report(excel_val_results, system_determined_latest_version)
            jira_tickets_str += f"\n\n**Excel vs PDF Comparison (Under Jira Validation):**\n{excel_report}"
        elif excel_val_results and "error" in excel_val_results:
            shown_path = excel_path_used or "None"
            error_msg = excel_val_results["error"]
            jira_tickets_str += f"\n\n**Excel vs PDF Comparison (Under Jira Validation):**\n### Excel vs Release Notes Validation\n*Excel comparison was skipped: {error_msg}*"
        else:
            shown_path = excel_path_used or "None"
            jira_tickets_str += f"\n\n**Excel vs PDF Comparison (Under Jira Validation):**\n### Excel vs Release Notes Validation\n*Excel comparison was skipped because no valid Excel path was provided. (Path provided: {shown_path})*"

        formatted_prompt = MASTER_PROMPT.format(
            source_pdf_file_name=os.path.basename(pdf_path),
            current_date=current_date,
            system_determined_latest_version=system_determined_latest_version,
            system_determined_release_type=release_type,
            system_determined_version_consistency=version_consistency,
            system_determined_version_details=version_details,
            system_determined_date_validation=date_validation_str,
            system_determined_jira_tickets=jira_tickets_str,
            system_determined_toc_validation=toc_validation_str,
        )
        
        print("Generating the validation report...")
        report_text = formatted_prompt

        # Process PDF links natively to avoid LLM token overhead and truncation
        pdf_links_section = "\n## 6. Internal Document Links\n"
        
        if not pdf_checks:
            pdf_links_section += "No internal PDF links found.\n"
        else:
            pdf_links_section += f"- **Total .pdf paths checked:** {total_paths}\n"
            pdf_links_section += f"- **Successfully opened:** {readable_count} | **Missing:** {not_found_count} | **Exists but failed to open:** {unreadable_count}\n\n"
            pdf_links_section += "*Note: Web browsers block direct links to local files for security. Please copy the paths and paste them into File Explorer.*\n\n"
            pdf_links_section += "**PDF links extracted from document:**\n"
            
            for check in pdf_checks:
                if check.get("readable") or check.get("status") == "PASS":
                    status_str = "✅ Successfully opened"
                elif not check.get("exists"):
                    http_status = check.get("http_status")
                    if http_status:
                        status_str = f"❌ HTTP Error {http_status}"
                    else:
                        status_str = "❌ File not found"
                else:
                    status_str = f"⚠️ Failed to open (Error: {check.get('error', 'Corrupted or unreadable')})"
                    
                display_path = check.get('raw_text', check.get('original_link', check.get('file_path')))
                resolved_path = check.get('file_path', display_path)
                
                # We no longer unquote display_path because we want it EXACTLY as it was in the PDF
                
                if isinstance(resolved_path, str) and resolved_path.lower().startswith(('http://', 'https://', 'mailto:')):
                    pdf_links_section += f"- Path: <a href=\"{resolved_path}\" target=\"_blank\">{display_path}</a> | Status: {status_str}\n"
                else:
                    # Render as an easy-to-copy code block since browsers block file:// execution
                    pdf_links_section += f"- Path: `{display_path}` | Status: {status_str}\n"

        report_text += "\n" + pdf_links_section
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        return report_text, output_path
