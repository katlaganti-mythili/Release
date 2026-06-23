import json
import os
import re
from datetime import datetime
from agents.version_validator import VersionValidator
from agents.validators.date_validator import DateValidator
from services.ollama_service import OllamaService
from services.jira_service import JiraService
from utils.version_utils import extract_version_from_change_summary

MASTER_PROMPT = """# Release Validation Report

## 1. File Summary
- **File:** {source_pdf_file_name}
- **Detected Latest Version:** {system_determined_latest_version}
- **Release Type:** {system_determined_release_type}

## 2. Version Validation & Change Summary
- **Latest Version Consistency:** {system_determined_version_consistency}
- **Details:** {system_determined_version_details}
- **Change Summary Latest Version Entry:** {system_determined_change_summary_latest_version}
- **Change Summary Date Match:** {system_determined_change_summary_date_match} (Does the date in the Change Summary exactly match {current_date}?)

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
                
                # Strictly match the header to avoid pulling in old releases that merely mention the new version
                if has_ver(base_version, key) or has_ver(norm_base, norm_key):
                    merged_key.append(key)
                    merged_tickets.update(data.get("tickets", []))
                    merged_content.append(data.get("content", ""))
                    
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
                found_pre = re.findall(r'\b([A-Za-z]{2,15}\s*-\s*\d+)\b', parts[0])
                global_tickets.update(t.upper().replace(' ', '') for t in found_pre)
                
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
                
                # Look for tickets in the entire block instead of just the content line
                # Standard Jira tickets: 2-15 uppercase letters followed by optional spaces, hyphen and digits
                found_tickets = re.findall(r'\b([A-Za-z]{2,15}\s*-\s*\d+)\b', clean_part)
                tickets = [t.upper().replace(' ', '') for t in found_tickets]
                
                if header not in results:
                    results[header] = {"tickets": set(), "content": ""}
                results[header]["tickets"].update(tickets)
                results[header]["content"] += "\n" + clean_part
                
        if global_tickets:
            results["GLOBAL_APPENDIX_TICKETS"] = {"tickets": list(global_tickets), "content": global_content_text}
                
        return {k: {"tickets": list(v["tickets"]), "content": v["content"]} for k, v in results.items()}

    def generate(self, state: dict, output_path="reports/validation_report.txt"):
        
        pdf_path = state.get("pdf_path", "Unknown")
        text = state.get("text", "")
        system_determined_latest_version = state.get("system_determined_latest_version", "Unknown")
        toc_validation = state.get("toc_validation", {})
        
        # Format as MM-DD-YYYY to match what user is seeing in the PDF
        current_date = datetime.today().strftime("%m-%d-%Y")
        
        # Extract Jira tickets grouped by exact Build Number blocks
        build_blocks = self.extract_build_blocks(text)
        
        # Check PDF links status to pass to LLM for final summary calculation
        pdf_checks = state.get("pdf_validation", [])
        pdf_missing = sum(1 for p in pdf_checks if not p.get("readable") and p.get("status") != "PASS")
        pdf_links_status = "FAIL (Contains broken or missing links)" if pdf_missing > 0 else "PASS"
        
        # Determine Version, Date, Jira Tickets, Release Type, and TOC status Deterministically
        # Extract the version strictly from the Change Summary to avoid false positives (e.g. IP addresses)
        latest_text_version = extract_version_from_change_summary(text) or "UNKNOWN"

        if latest_text_version == "UNKNOWN":
            version_consistency = "FAIL"
            version_details = "No versions were found in the document's change summary."
        elif latest_text_version == system_determined_latest_version:
            version_consistency = "PASS"
            version_details = f"The latest version found in the document ({latest_text_version}) matches the expected latest version."
        else:
            version_consistency = "FAIL"
            version_details = (
                f"The latest version found in the Change Summary ({latest_text_version}) does not match "
                f"the expected latest version ({system_determined_latest_version}). Historical older versions are ignored."
            )
            
        change_summary_latest_version = (
            "CORRECT" if latest_text_version == system_determined_latest_version
            else f"INCORRECT (Found {latest_text_version}, expected {system_determined_latest_version})"
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
            change_summary_date_match = "YES"
            date_validation_str = f"- **Status:** VALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date matches the expected date."
        elif date_status == "PAST":
            change_summary_date_match = "NO"
            date_validation_str = f"- **Status:** INVALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date is a previous date ({relation})."
        elif date_status == "FUTURE":
            change_summary_date_match = "NO"
            date_validation_str = f"- **Status:** INVALID\n- **Result:** {date_msg}, expected date: {current_date}\n- **Details:** The extracted date is a future date ({relation})."
        else:
            change_summary_date_match = "NO"
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
            print(f"Validating {len(matching_block)} extracted Jira tickets against live Jira board...")
            
            import concurrent.futures
            
            def check_ticket(t):
                is_valid = self.jira_service.ticket_exists(t)
                status = "[Verified in Jira]" if is_valid else "[NOT FOUND in Jira]"
                return f"- jira ticket found ({system_determined_latest_version}): {t} {status}"
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
                results = list(executor.map(check_ticket, matching_block))
                
            jira_lines.extend(results)
            jira_tickets_str = "\n".join(jira_lines)
        else:
            jira_tickets_str = "jira ticket not found in pdf"

        formatted_prompt = MASTER_PROMPT.format(
            source_pdf_file_name=os.path.basename(pdf_path),
            current_date=current_date,
            system_determined_latest_version=system_determined_latest_version,
            system_determined_release_type=release_type,
            system_determined_version_consistency=version_consistency,
            system_determined_version_details=version_details,
            system_determined_change_summary_latest_version=change_summary_latest_version,
            system_determined_change_summary_date_match=change_summary_date_match,
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
            total_paths = len(pdf_checks)
            valid_paths = sum(1 for p in pdf_checks if p.get("readable") or p.get("status") == "PASS")
            missing_paths = sum(1 for p in pdf_checks if not p.get("exists"))
            invalid_format = 0  # Assuming all passed to validate were .pdf since we filtered earlier
            
            pdf_links_section += f"- **Total .pdf paths checked:** {total_paths}\n"
            pdf_links_section += f"- **Valid .pdf paths:** {valid_paths} | **Missing .pdf paths:** {missing_paths} | **Invalid format:** {invalid_format} | **Pdfs able to open:** {valid_paths}\n\n"
            pdf_links_section += "**PDF links extracted from document:**\n"
            
            for check in pdf_checks:
                status_str = "opened" if check.get("readable") or check.get("status") == "PASS" else "not opened"
                # Output raw path without backticks to make it easier to copy-paste cleanly in Windows
                display_path = check.get('original_link', check.get('file_path'))
                pdf_links_section += f"- Path: {display_path} | Status: {status_str}\n"

        report_text += "\n" + pdf_links_section
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        return report_text, output_path
