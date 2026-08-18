import os
import re
import logging
import html
import openpyxl
import pandas as pd
import pdfplumber

logger = logging.getLogger(__name__)

TICKET_ID_PATTERN = re.compile(
    r"(?i)\b((?:MNOSD|WAMAT)\s*[-–—]\s*\d+(?:\s*[-–—]\s*\d+)*(?:[A-Z])?)(?:\s*(?:BUG|SWG))?\b"
)


class JiraExcelValidator:
    def __init__(self):
        self.last_read_error = ""

    def normalize_ticket_identifier(self, value):
        """
        Canonicalize ticket-like identifiers used for matching between Excel and PDF.
        Handles common OCR/text artifacts like trailing BUG/SWG tags.
        """
        text = self.normalize(value).upper()
        text = text.replace("–", "-").replace("—", "-")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"(BUG|SWG)$", "", text)
        return text

    def extract_ticket_ids_from_text(self, value):
        if value is None:
            return set()
        raw = self.normalize(value)
        found = TICKET_ID_PATTERN.findall(raw)
        return {self.normalize_ticket_identifier(t).lower() for t in found if t}

    def normalize(self, value):
        if value is None or pd.isna(value):
            return ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        value = str(value)
        value = re.sub(r"\s+", " ", value.replace("\n", " "))
        return value.strip()

    def normalize_compare(self, value):
        return self.normalize(value).lower()

    def extract_application_name(self, pdf_filename):
        """
        Extracts application name from PDF filename.
        Handles patterns like:
        - 'OpenGrid <version> <App Name> Release Notes.pdf'
        - '<App Name> Release Notes.pdf'
        - '<version> <App Name> Release Notes.pdf'
        """
        filename = os.path.basename(pdf_filename)

        # 1. OpenGrid pattern with version: "OpenGrid 2.3.10.7[1] Asset Manager Release Notes"
        pattern = r"(?:OpenGrid\s+)?[\d\.]+(?:\[\d+\])?(?:[\s\-]*Patch\s*\d+)?(?:[\s\-]*Hotfix\s*\d+)?\s+(.*?)\s+Release\s+Notes"
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return self.normalize(match.group(1))

        # 2. OpenGrid pattern without version
        pattern2 = r"OpenGrid\s+(.*?)\s+Release\s+Notes"
        match2 = re.search(pattern2, filename, re.IGNORECASE)
        if match2:
            return self.normalize(match2.group(1))

        # 3. Just <App Name> Release Notes
        pattern3 = r"(.*?)\s+Release\s+Notes"
        match3 = re.search(pattern3, filename, re.IGNORECASE)
        if match3:
            return self.normalize(match3.group(1))

        # 4. Fallback: remove version prefix like "2.3.10.7[1]" or "OpenGrid 2.3.10.7[1]"
        fallback = filename.replace(".pdf", "").replace(".PDF", "")
        fallback = re.sub(r"^(?:OpenGrid\s+)?[\d\.]+(?:\[\d+\])?(?:[\s\-]*Patch\s*\d+)?(?:[\s\-]*Hotfix\s*\d+)?\s*", "", fallback, flags=re.IGNORECASE).strip()
        fallback = re.sub(r"\s+Release\s+Notes.*", "", fallback, flags=re.IGNORECASE).strip()
        if fallback:
            return self.normalize(fallback)

        return self.normalize(filename.replace(".pdf", "").replace(".PDF", ""))

    def read_excel(self, excel_path):
        self.last_read_error = ""

        if not excel_path:
            self.last_read_error = "Excel file path was not provided."
            logger.error(self.last_read_error)
            return []

        if not os.path.exists(excel_path):
            self.last_read_error = f"Excel file does not exist: {excel_path}"
            logger.error(self.last_read_error)
            return []

        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True, read_only=True)
        except Exception as e:
            self.last_read_error = f"Error reading Excel workbook: {e}"
            logger.error(self.last_read_error)
            return []

        try:
            records = []
            header_keywords = ["account", "ssc", "description", "client tracking", "application", "functional"]

            for ws in wb.worksheets:
                current_headers = []
                current_app = ""
                in_data_section = False

                for row in ws.iter_rows(values_only=True):
                    row_vals = [self.normalize(cell) for cell in row]
                    row_lower = [v.lower() for v in row_vals]

                    # Check if this row is a header row.
                    match_count = sum(1 for kw in header_keywords if any(kw in v for v in row_lower))
                    if match_count >= 2:
                        current_headers = row_vals
                        current_app = ""
                        in_data_section = True
                        continue

                    if not in_data_section:
                        continue

                    if all(v == "" for v in row_vals):
                        continue

                    row_dict = {}
                    for idx, h in enumerate(current_headers):
                        if idx < len(row_vals) and h:
                            row_dict[h.lower()] = row_vals[idx]

                    app_val = ""
                    for k, v in row_dict.items():
                        if "application name" in k or "application" in k:
                            app_val = v
                            break

                    if app_val:
                        current_app = app_val

                    account_name = ""
                    client_tracking = ""
                    ssc_id = ""
                    desc = ""
                    functional = ""

                    for k, v in row_dict.items():
                        if "account name" in k:
                            account_name = v
                        elif "client tracking" in k:
                            client_tracking = v
                        elif "ssc id" in k or "ssc" in k:
                            ssc_id = v
                        elif "issue description" in k or "description" in k:
                            desc = v
                        elif "functional model" in k:
                            functional = v

                    records.append({
                        "application": current_app,
                        "account_name": account_name,
                        "client_tracking_number": client_tracking,
                        "ssc_id": ssc_id,
                        "description": desc,
                        "functional_model": functional
                    })

            return records
        finally:
            wb.close()
    def filter_application_records(self, records, application_name):
        """
        Filter Excel records by application name using strict normalized equality.
        If no strict matches are found, falls back to substring matching.
        """
        filtered = []
        target_app = self.normalize_compare(application_name)
        target_app_no_spaces = target_app.replace(" ", "")

        for r in records:
            app_val = self.normalize_compare(r.get("application", ""))
            if target_app == app_val:
                filtered.append(r)
                
        if not filtered:
            for r in records:
                app_val = self.normalize_compare(r.get("application", ""))
                app_val_no_spaces = app_val.replace(" ", "")
                if target_app in app_val or (app_val and app_val in target_app) or \
                   (target_app_no_spaces and target_app_no_spaces in app_val_no_spaces) or \
                   (app_val_no_spaces and app_val_no_spaces in target_app_no_spaces):
                    filtered.append(r)
                    
        return filtered

    def extract_pdf_table(self, pdf_path):
        records = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if not table:
                            continue

                        header_index = None
                        for i, row in enumerate(table):
                            row_text = " ".join(str(x) for x in row if x).lower()
                            keywords = ["ssc id", "issue description", "client tracking", "account name", "functional model"]
                            if sum(1 for kw in keywords if kw in row_text) >= 2:
                                header_index = i
                                break

                        if header_index is None:
                            continue

                        headers = [self.normalize(x) for x in table[header_index]]
                        for row in table[header_index+1:]:
                            if not any(row):
                                continue

                            data = {}
                            for idx, h in enumerate(headers):
                                value = ""
                                if idx < len(row):
                                    value = row[idx]
                                data[h] = self.normalize(value)

                            if data:
                                records.append(data)
        except Exception as e:
            logger.error(f"Failed to extract table from PDF: {e}")
        return records

    def create_key(self, row, source_type="excel"):
        if source_type == "excel":
            ssc = self.normalize_ticket_identifier(row.get("ssc_id", ""))
            ctn = self.normalize_ticket_identifier(row.get("client_tracking_number", ""))
            desc = self.normalize(row.get("description", ""))
            ticket_blob = " ".join([
                row.get("ssc_id", "") or "",
                row.get("client_tracking_number", "") or "",
                row.get("description", "") or "",
            ])
        else:
            ssc = ""
            ctn = ""
            desc = ""
            ticket_blob_parts = []
            for k, v in row.items():
                kl = k.lower()
                if "ssc id" in kl or "ssc" in kl:
                    ssc = self.normalize_ticket_identifier(v)
                elif "client tracking" in kl:
                    ctn = self.normalize_ticket_identifier(v)
                elif "issue description" in kl or "description" in kl:
                    desc = self.normalize(v)
                ticket_blob_parts.append(self.normalize(v))
            ticket_blob = " ".join(ticket_blob_parts)

        extracted_tickets = sorted(self.extract_ticket_ids_from_text(ticket_blob))
        if extracted_tickets:
            return f"ticket_{extracted_tickets[0]}"

        if ssc:
            return f"ssc_{ssc.lower()}"
        if ctn:
            return f"ctn_{ctn.lower()}"
        if desc:
            return f"desc_{desc.lower()[:50]}"
        return ""

    def compare(self, excel_records, pdf_records, application):
        result = []
        pdf_unmatched = list(pdf_records)
        excel_unmatched = list(excel_records)
        paired = []

        def get_tickets(row, source_type):
            if source_type == "excel":
                blob = " ".join([str(row.get("ssc_id", "") or ""), str(row.get("client_tracking_number", "") or ""), str(row.get("description", "") or "")])
            else:
                blob = " ".join(str(v) for v in row.values())
            return self.extract_ticket_ids_from_text(blob)

        # Pass 1: match by ticket ids
        for ex in excel_unmatched[:]:
            ex_tickets = get_tickets(ex, "excel")
            if not ex_tickets:
                continue
            matched_pd = None
            for pd in pdf_unmatched:
                pd_tickets = get_tickets(pd, "pdf")
                if ex_tickets.intersection(pd_tickets):
                    matched_pd = pd
                    break
            if matched_pd:
                paired.append((ex, matched_pd))
                excel_unmatched.remove(ex)
                pdf_unmatched.remove(matched_pd)

        # Pass 2: match by exact string match of SSC or CTN
        for ex in excel_unmatched[:]:
            ex_ssc = self.normalize_ticket_identifier(ex.get("ssc_id", ""))
            ex_ctn = self.normalize_ticket_identifier(ex.get("client_tracking_number", ""))
            matched_pd = None
            for pd in pdf_unmatched:
                pd_ssc = ""
                pd_ctn = ""
                for k, v in pd.items():
                    kl = k.lower()
                    if "ssc id" in kl or ("ssc" in kl and "ssc id" not in kl):
                        pd_ssc = self.normalize_ticket_identifier(v)
                    elif "client tracking" in kl:
                        pd_ctn = self.normalize_ticket_identifier(v)
                
                if (ex_ssc and pd_ssc and ex_ssc == pd_ssc) or (ex_ctn and pd_ctn and ex_ctn == pd_ctn):
                    matched_pd = pd
                    break
            if matched_pd:
                paired.append((ex, matched_pd))
                excel_unmatched.remove(ex)
                pdf_unmatched.remove(matched_pd)

        # Pass 3: Force-pair remaining unmapped rows side-by-side
        max_len = max(len(excel_unmatched), len(pdf_unmatched))
        for i in range(max_len):
            ex = excel_unmatched[i] if i < len(excel_unmatched) else {}
            pd_row = pdf_unmatched[i] if i < len(pdf_unmatched) else {}
            paired.append((ex, pd_row))

        def extract_pdf_fields(row):
            pdf_account = ""
            pdf_ctn = ""
            pdf_ssc = ""
            pdf_desc = ""
            pdf_functional = ""

            for k, v in row.items():
                kl = k.lower()
                if "account name" in kl:
                    pdf_account = self.normalize(v)
                elif "client tracking" in kl:
                    pdf_ctn = self.normalize(v)
                elif "ssc id" in kl or ("ssc" in kl and "ssc id" not in kl):
                    pdf_ssc = self.normalize(v)
                elif "issue description" in kl or "description" in kl:
                    pdf_desc = self.normalize(v)
                elif "functional model" in kl:
                    pdf_functional = self.normalize(v)

            return pdf_account, pdf_ctn, pdf_ssc, pdf_desc, pdf_functional

        for ex, pd_row in paired:
            pdf_account, pdf_ctn, pdf_ssc, pdf_desc, pdf_functional = extract_pdf_fields(pd_row) if pd_row else ("", "", "", "", "")

            status = "PASS"
            remarks = []

            comparison = {
                "Application Name (Excel)": ex.get("application", "") if ex else "",
                "Application Name (PDF)": application,
                "Account Name (Excel)": ex.get("account_name", "") if ex else "",
                "Account Name (PDF)": pdf_account,
                "Client Tracking Number (Excel)": ex.get("client_tracking_number", "") if ex else "",
                "Client Tracking Number (PDF)": pdf_ctn,
                "SSC ID (Excel)": ex.get("ssc_id", "") if ex else "",
                "SSC ID (PDF)": pdf_ssc,
                "Issue Description (Excel)": ex.get("description", "") if ex else "",
                "Issue Description (PDF)": pdf_desc,
                "Functional Model (Excel)": ex.get("functional_model", "") if ex else "",
                "Functional Model (PDF)": pdf_functional,
            }

            if not pd_row:
                status = "Missing in PDF"
                remarks.append("Missing in PDF")
            elif not ex:
                status = "Missing in Excel"
                remarks.append("Missing in Excel")
            else:
                if self.normalize_compare(comparison["Account Name (Excel)"]) != self.normalize_compare(comparison["Account Name (PDF)"]):
                    status = "FAIL"
                    remarks.append(f"Account Name mismatch (Excel: '{comparison['Account Name (Excel)']}' vs PDF: '{comparison['Account Name (PDF)']}')")
                if (
                    self.normalize_ticket_identifier(comparison["Client Tracking Number (Excel)"])
                    != self.normalize_ticket_identifier(comparison["Client Tracking Number (PDF)"])
                ):
                    status = "FAIL"
                    remarks.append(f"Client Tracking Number mismatch (Excel: '{comparison['Client Tracking Number (Excel)']}' vs PDF: '{comparison['Client Tracking Number (PDF)']}')")
                if (
                    self.normalize_ticket_identifier(comparison["SSC ID (Excel)"])
                    != self.normalize_ticket_identifier(comparison["SSC ID (PDF)"])
                ):
                    status = "FAIL"
                    remarks.append(f"SSC ID mismatch (Excel: '{comparison['SSC ID (Excel)']}' vs PDF: '{comparison['SSC ID (PDF)']}')")
                if self.normalize_compare(comparison["Issue Description (Excel)"]) != self.normalize_compare(comparison["Issue Description (PDF)"]):
                    status = "FAIL"
                    remarks.append("Issue Description mismatch")
                if self.normalize_compare(comparison["Functional Model (Excel)"]) != self.normalize_compare(comparison["Functional Model (PDF)"]):
                    status = "FAIL"
                    remarks.append("Functional Model mismatch")

                ex_t = get_tickets(ex, "excel")
                pd_t = get_tickets(pd_row, "pdf")
                ex_ssc_norm = self.normalize_ticket_identifier(comparison["SSC ID (Excel)"])
                pd_ssc_norm = self.normalize_ticket_identifier(comparison["SSC ID (PDF)"])
                
                if not (ex_t and pd_t and ex_t.intersection(pd_t)) and not (ex_ssc_norm and pd_ssc_norm and ex_ssc_norm == pd_ssc_norm):
                     status = "FAIL"
                     if "Unmapped Row Pair (Force Joined)" not in remarks:
                         remarks.append("Unmapped Row Pair (Force Joined)")

            comparison["Status"] = status
            comparison["Remarks"] = "; ".join(remarks) if remarks else "Matched"
            result.append(comparison)

        return result

    def validate(self, pdf_path, excel_path, matching_block=None, app_name_hint=None, fuzzy_threshold=0.75, *args, **kwargs):
        application = self.extract_application_name(pdf_path)
        if not application and app_name_hint:
            application = self.extract_application_name(app_name_hint)
        if not application:
            return {"error": "Could not extract Application Name from PDF filename."}

        if not excel_path or not os.path.exists(excel_path):
            return {"error": "Excel file path was not provided or is not accessible to the app session."}

        excel_records = self.read_excel(excel_path)
        if not excel_records:
            if self.last_read_error:
                return {"error": self.last_read_error}
            return {"error": "Excel file was found but no Jira data rows could be parsed from the worksheet headers."}

        # Keep fuzzy_threshold in the signature for backward compatibility, but use strict matching.
        filtered_excel = self.filter_application_records(excel_records, application)
        if not filtered_excel:
            return {"error": f"No matching Application Name found in Excel for '{application}'."}

        pdf_records = self.extract_pdf_table(pdf_path)

        comparison = self.compare(filtered_excel, pdf_records, application)

        # Restrict records to only tickets found in the latest version block (Jira validation output)
        if matching_block:
            norm_matching = {self.normalize_ticket_identifier(t).lower() for t in matching_block}
            filtered_comparison = []
            
            for comp in comparison:
                excel_ssc = self.normalize_ticket_identifier(comp.get("SSC ID (Excel)", "")).lower()
                pdf_ssc = self.normalize_ticket_identifier(comp.get("SSC ID (PDF)", "")).lower()
                excel_ctn = self.normalize_ticket_identifier(comp.get("Client Tracking Number (Excel)", "")).lower()
                pdf_ctn = self.normalize_ticket_identifier(comp.get("Client Tracking Number (PDF)", "")).lower()
                
                excel_desc = str(comp.get("Issue Description (Excel)", "")).lower()
                pdf_desc = str(comp.get("Issue Description (PDF)", "")).lower()
                
                excel_tickets = self.extract_ticket_ids_from_text(str(comp.get("SSC ID (Excel)", "")) + " " + excel_desc)
                pdf_tickets = self.extract_ticket_ids_from_text(str(comp.get("SSC ID (PDF)", "")) + " " + pdf_desc)

                if (
                    excel_ssc in norm_matching or pdf_ssc in norm_matching
                    or excel_ctn in norm_matching or pdf_ctn in norm_matching
                    or excel_tickets.intersection(norm_matching)
                    or pdf_tickets.intersection(norm_matching)
                ):
                    filtered_comparison.append(comp)
                elif any(t in excel_desc or t in pdf_desc for t in norm_matching if t):
                    filtered_comparison.append(comp)

            comparison = filtered_comparison

        matched_records = sum(1 for c in comparison if c["Status"] == "PASS")
        failed_records = sum(1 for c in comparison if c["Status"] == "FAIL")
        missing_in_pdf = sum(1 for c in comparison if "Missing in PDF" in c.get("Remarks", ""))
        missing_in_excel = sum(1 for c in comparison if "Missing in Excel" in c.get("Remarks", ""))

        overall_status = "PASS" if failed_records == 0 and missing_in_pdf == 0 and missing_in_excel == 0 else "FAIL"

        return {
            "application": application,
            "total_excel_records": len([c for c in comparison if c.get("Application Name (Excel)")]),
            "total_pdf_records": len([c for c in comparison if c.get("Application Name (PDF)")]),
            "matched_records": matched_records,
            "failed_records": failed_records,
            "missing_in_pdf": missing_in_pdf,
            "missing_in_excel": missing_in_excel,
            "overall_status": overall_status,
            "comparison": comparison
        }

    def format_report(self, val_result, latest_version=""):
        if not val_result:
            return "No validation results provided."

        if "error" in val_result:
            return f"**Excel Validation Skipped:**\n{val_result['error']}"

        app = val_result.get("application", "")
        
        output = []
        output.append("### Excel vs Release Notes Validation\n")
        output.append(f"**Latest Build Number:** {latest_version}\n")
        
        # Check for Duplicate SSC IDs in PDF comparison for future-proofing, though current logic doesn't strictly track duplicates well.
        # We can just say "None" for now or calculate it.
        # Simple duplicate check on Excel SSC IDs:
        ssc_ids = []
        if val_result.get("comparison"):
            for row in val_result["comparison"]:
                if row.get("SSC ID"):
                    ssc_ids.append(row["SSC ID"])
        
        import collections
        duplicates = [item for item, count in collections.Counter(ssc_ids).items() if count > 1]
        dup_str = ", ".join(duplicates) if duplicates else "None"
        output.append(f"**Duplicate SSC IDs:** {dup_str}\n")
        
        mismatches = []
        differences = []
        full_rows = []
        col_status = {
            "Account Name": "PASS",
            "Client Tracking Number": "PASS",
            "SSC ID": "PASS",
            "Issue Description": "PASS",
            "Functional Model": "PASS"
        }
        
        if val_result.get("comparison"):
            for row in val_result["comparison"]:
                status_value = row.get("Status", "")
                remarks = row.get("Remarks", "")
                full_rows.append({
                    "application_excel": row.get("Application Name (Excel)", ""),
                    "application_pdf": row.get("Application Name (PDF)", app),
                    "account_excel": row.get("Account Name (Excel)", ""),
                    "account_pdf": row.get("Account Name (PDF)", ""),
                    "ctn_excel": row.get("Client Tracking Number (Excel)", ""),
                    "ctn_pdf": row.get("Client Tracking Number (PDF)", ""),
                    "ssc_excel": row.get("SSC ID (Excel)", ""),
                    "ssc_pdf": row.get("SSC ID (PDF)", ""),
                    "desc_excel": row.get("Issue Description (Excel)", ""),
                    "desc_pdf": row.get("Issue Description (PDF)", ""),
                    "fm_excel": row.get("Functional Model (Excel)", ""),
                    "fm_pdf": row.get("Functional Model (PDF)", ""),
                    "status": status_value,
                    "remarks": remarks,
                })

                identifier = (
                    row.get("SSC ID (Excel)")
                    or row.get("SSC ID (PDF)")
                    or row.get("Client Tracking Number (Excel)")
                    or row.get("Client Tracking Number (PDF)")
                    or row.get("Issue Description (Excel)")
                    or row.get("Issue Description (PDF)")
                    or ""
                )

                if status_value != "PASS":
                    differences.append({
                        "identifier": identifier,
                        "status": status_value,
                        "account_excel": row.get("Account Name (Excel)", ""),
                        "account_pdf": row.get("Account Name (PDF)", ""),
                        "ctn_excel": row.get("Client Tracking Number (Excel)", ""),
                        "ctn_pdf": row.get("Client Tracking Number (PDF)", ""),
                        "ssc_excel": row.get("SSC ID (Excel)", ""),
                        "ssc_pdf": row.get("SSC ID (PDF)", ""),
                        "desc_excel": row.get("Issue Description (Excel)", ""),
                        "desc_pdf": row.get("Issue Description (PDF)", ""),
                        "fm_excel": row.get("Functional Model (Excel)", ""),
                        "fm_pdf": row.get("Functional Model (PDF)", ""),
                        "remarks": remarks,
                    })

                if row.get("Status") == "FAIL":
                    ssc = row.get("SSC ID (Excel)") or row.get("SSC ID (PDF)") or ""
                    
                    if "Account Name mismatch" in remarks:
                        mismatches.append(
                            f"| {ssc} | Account Name | {row.get('Account Name (Excel)', '')} | {row.get('Account Name (PDF)', '')} | ❌ FAILED |"
                        )
                        col_status["Account Name"] = "FAIL"
                        
                    if "Client Tracking Number mismatch" in remarks:
                        mismatches.append(
                            f"| {ssc} | Client Tracking Number | {row.get('Client Tracking Number (Excel)', '')} | {row.get('Client Tracking Number (PDF)', '')} | ❌ FAILED |"
                        )
                        col_status["Client Tracking Number"] = "FAIL"
                        
                    if "SSC ID mismatch" in remarks:
                        mismatches.append(
                            f"| {ssc} | SSC ID | {row.get('SSC ID (Excel)', '')} | {row.get('SSC ID (PDF)', '')} | ❌ FAILED |"
                        )
                        col_status["SSC ID"] = "FAIL"
                        
                    if "Issue Description mismatch" in remarks:
                        mismatches.append(
                            f"| {ssc} | Issue Description | {row.get('Issue Description (Excel)', '')} | {row.get('Issue Description (PDF)', '')} | ❌ FAILED |"
                        )
                        col_status["Issue Description"] = "FAIL"
                        
                    if "Functional Model mismatch" in remarks:
                        mismatches.append(
                            f"| {ssc} | Functional Model | {row.get('Functional Model (Excel)', '')} | {row.get('Functional Model (PDF)', '')} | ❌ FAILED |"
                        )
                        col_status["Functional Model"] = "FAIL"

        if full_rows:
            output.append("#### Full Comparison Table")
            output.append("<table>")
            output.append("<thead><tr><th>Application Name (Excel)</th><th>Application Name (PDF)</th><th>Account Name (Excel)</th><th>Account Name (PDF)</th><th>Client Tracking Number (Excel)</th><th>Client Tracking Number (PDF)</th><th>SSC ID (Excel)</th><th>SSC ID (PDF)</th><th>Issue Description (Excel)</th><th>Issue Description (PDF)</th><th>Functional Model (Excel)</th><th>Functional Model (PDF)</th><th>Status</th><th>Remarks</th></tr></thead>")
            output.append("<tbody>")
            for r in full_rows:
                output.append(
                    "<tr>"
                    f"<td>{html.escape(str(r['application_excel']))}</td>"
                    f"<td>{html.escape(str(r['application_pdf']))}</td>"
                    f"<td>{html.escape(str(r['account_excel']))}</td>"
                    f"<td>{html.escape(str(r['account_pdf']))}</td>"
                    f"<td>{html.escape(str(r['ctn_excel']))}</td>"
                    f"<td>{html.escape(str(r['ctn_pdf']))}</td>"
                    f"<td>{html.escape(str(r['ssc_excel']))}</td>"
                    f"<td>{html.escape(str(r['ssc_pdf']))}</td>"
                    f"<td>{html.escape(str(r['desc_excel']))}</td>"
                    f"<td>{html.escape(str(r['desc_pdf']))}</td>"
                    f"<td>{html.escape(str(r['fm_excel']))}</td>"
                    f"<td>{html.escape(str(r['fm_pdf']))}</td>"
                    f"<td>{html.escape(str(r['status']))}</td>"
                    f"<td>{html.escape(str(r['remarks']))}</td>"
                    "</tr>"
                )
            output.append("</tbody>")
            output.append("</table>")
            output.append("")

        if mismatches:
            output.append("#### Field-Level Mismatches")
            output.append("| SSC ID / Identifier | Field | Excel Value | PDF Value | Status |")
            output.append("|---|---|---|---|---|")
            output.extend(mismatches)
            output.append("")

        if differences:
            output.append("#### Mismatched Details (Missing/Failed Rows)")
            output.append("<table>")
            output.append("<thead><tr><th>SSC ID / Identifier</th><th>Status</th><th>Account Name (Excel)</th><th>Account Name (PDF)</th><th>Client Tracking Number (Excel)</th><th>Client Tracking Number (PDF)</th><th>SSC ID (Excel)</th><th>SSC ID (PDF)</th><th>Issue Description (Excel)</th><th>Issue Description (PDF)</th><th>Functional Model (Excel)</th><th>Functional Model (PDF)</th><th>Remarks</th></tr></thead>")
            output.append("<tbody>")
            for d in differences:
                output.append(
                    "<tr>"
                    f"<td>{html.escape(str(d.get('identifier', '')))}</td>"
                    f"<td>{html.escape(str(d.get('status', '')))}</td>"
                    f"<td>{html.escape(str(d.get('account_excel', '')))}</td>"
                    f"<td>{html.escape(str(d.get('account_pdf', '')))}</td>"
                    f"<td>{html.escape(str(d.get('ctn_excel', '')))}</td>"
                    f"<td>{html.escape(str(d.get('ctn_pdf', '')))}</td>"
                    f"<td>{html.escape(str(d.get('ssc_excel', '')))}</td>"
                    f"<td>{html.escape(str(d.get('ssc_pdf', '')))}</td>"
                    f"<td>{html.escape(str(d.get('desc_excel', '')))}</td>"
                    f"<td>{html.escape(str(d.get('desc_pdf', '')))}</td>"
                    f"<td>{html.escape(str(d.get('fm_excel', '')))}</td>"
                    f"<td>{html.escape(str(d.get('fm_pdf', '')))}</td>"
                    f"<td>{html.escape(str(d.get('remarks', '')))}</td>"
                    "</tr>"
                )
            output.append("</tbody>")
            output.append("</table>")
            output.append("")
        elif full_rows:
            output.append("#### Mismatched Details")
            output.append("No mismatches found.")
            output.append("")
            
        output.append("#### Column Check Summary")
        output.append("| Column | Match Status |")
        output.append("|--------|--------------|")
        for col, status in col_status.items():
            icon = "✔ PASS" if status == "PASS" else "✖ FAIL"
            output.append(f"| {col} | {icon} |")
            
        output.append("\n#### Overall Result")
        overall = "**FAILED**" if val_result.get("overall_status") == "FAIL" else "**PASSED**"
        output.append(overall)
        
        if val_result.get("failed_records", 0) > 0:
            output.append(f"\nReason: {val_result.get('failed_records')} row(s) contain mismatched data.")
        elif val_result.get("missing_in_pdf", 0) > 0:
            output.append(f"\nReason: {val_result.get('missing_in_pdf')} row(s) missing in PDF.")
        elif val_result.get("missing_in_excel", 0) > 0:
            output.append(f"\nReason: {val_result.get('missing_in_excel')} row(s) missing in Excel.")

        return "\n".join(output)
