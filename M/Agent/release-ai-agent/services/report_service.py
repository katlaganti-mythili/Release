import json
import os
import re
from datetime import datetime
from agents.version_validator import VersionValidator
from agents.validators.date_validator import DateValidator
from services.ollama_service import OllamaService
from services.jira_service import JiraService

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

        if latest_version and latest_version != "Unknown":
            for key, data in build_blocks.items():
                # Normalize [N] bracket notation to .N so "2.3.10.7.1" matches "2.3.10.7[1]; …"
                normalized_key = re.sub(r"\[(\d+)\]", r".\1", key)
                if latest_version in normalized_key or latest_version in key:
                    return key, data

        first_key = next(iter(build_blocks))
        return first_key, build_blocks[first_key]

    def extract_build_blocks(self, text: str) -> dict:
        results = {}
        # Find Appendices A and B specifically to narrow search
        appendix_pattern = re.compile(r'(Appendix\s+[AB].*?)(?=Appendix\s+[C-Z]|$)', re.DOTALL | re.IGNORECASE)
        appendices = appendix_pattern.findall(text)
        
        search_areas = appendices if appendices else [text]
        
        for area in search_areas:
            parts = re.split(r'Build\s+Number:\s*(?:(?:ARM|OpenGrid)\s*)?', area, flags=re.IGNORECASE)
            for part in parts[1:]:
                # Extract up to the first newline
                lines = part.strip().split('\n', 1)
                if not lines:
                    continue
                header = lines[0].strip() # e.g. "4.0; 05-22-2026"
                content = lines[1] if len(lines) > 1 else ""
                
                # Only look for MNOSD or WAMAT in this specific block
                tickets = list(set(re.findall(r'((?:MNOSD|WAMAT)-\d+)', content)))
                
                if header not in results:
                    results[header] = {"tickets": set(), "content": ""}
                results[header]["tickets"].update(tickets)
                results[header]["content"] += "\n" + content
                
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
        version_result = self.version_validator.validate(text)
        latest_text_version = version_result.get("latest_version", "UNKNOWN")

        if latest_text_version == "UNKNOWN":
            version_consistency = "FAIL"
            version_details = "No versions were found in the document text."
        elif latest_text_version == system_determined_latest_version:
            version_consistency = "PASS"
            version_details = f"The latest version found in the document ({latest_text_version}) matches the expected latest version."
        else:
            version_consistency = "FAIL"
            version_details = (
                f"The highest version found in the document ({latest_text_version}) does not match "
                f"the expected latest version ({system_determined_latest_version}). Historical older versions are ignored."
            )

        change_summary_latest_version = (
            f"CORRECT ({system_determined_latest_version})"
            if latest_text_version == system_determined_latest_version
            else f"INCORRECT (Found {latest_text_version}, expected {system_determined_latest_version})"
        )

        date_validation_str = ""
        jira_tickets_str = ""
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
        date_source_text = f"{intro_text}\n{block_text}" if block_text else text

        date_result = self.date_validator.validate(date_source_text)
        date_found = date_result.get("normalized_release_date", "Not Found")
        raw_date = date_result.get("release_date", "Not Found")
        relation = date_result.get("relation", "unknown")
        date_status = date_result.get("status", "NOT_FOUND")

        path_lower = pdf_path.lower()
        if 'hf' in path_lower or 'hotfix' in path_lower or 'hf' in latest_block_content or 'hotfix' in latest_block_content:
            release_type = "HOTFIX"
        elif re.search(r'\bp\d+\b', path_lower) or 'patch' in path_lower or re.search(r'\bp\d+\b', latest_block_content) or 'patch' in latest_block_content:
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
                # Check if latest version appears in this section (normalize bracket notation)
                latest_present = any(
                    re.sub(r"\[(\d+)\]", r".\1", v) == system_determined_latest_version
                    for v in vers
                )
                latest_cell = "Present" if latest_present else "Not found"
                # Show first 3 dates (trim older historical ones if too many)
                dates_cell = ", ".join(sorted(set(dates))[:3]) if dates else "-"
                toc_validation_str += (
                    f"| {e.get('heading', '')} | {e.get('page', '')} | {nav} "
                    f"| {latest_cell} | {dates_cell} |\n"
                )
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
                "- **Details:** TOC validation did not run."
            )

        if matching_block:
            jira_lines = []
            print(f"Validating {len(matching_block)} extracted Jira tickets against live Jira board...")
            
            import concurrent.futures
            
            def check_ticket(t):
                is_valid = self.jira_service.ticket_exists(t)
                status = "[Verified in Jira]" if is_valid else "[NOT FOUND in Jira]"
                return f"- jira ticket found ({system_determined_latest_version}): {t} {status}"
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
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
            pdf_links_section += "**PDF links after adding root path:**\n"
            
            for check in pdf_checks:
                status_str = "opened" if check.get("readable") or check.get("status") == "PASS" else "not opened"
                # Output raw path without backticks to make it easier to copy-paste cleanly in Windows
                pdf_links_section += f"- Path: {check.get('file_path')} | Status: {status_str}\n"

        report_text += "\n" + pdf_links_section
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
            
        return report_text, output_path
