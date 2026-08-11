import argparse
import os
import sys
from pathlib import Path

from agents.validators.jira_excel_validator import JiraExcelValidator


FULL_TABLE_HEADERS = [
    "Application Name",
    "Account Name",
    "Client Tracking Number",
    "SSC ID",
    "Issue Description (Excel)",
    "Issue Description (PDF)",
    "Functional Model (Excel)",
    "Functional Model (PDF)",
    "Status",
    "Remarks",
]

DIFF_TABLE_HEADERS = [
    "Application Name",
    "SSC ID",
    "Account Name",
    "Client Tracking Number",
    "Issue Description (Excel)",
    "Issue Description (PDF)",
    "Functional Model (Excel)",
    "Functional Model (PDF)",
    "Status",
    "Remarks",
]


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run an Excel-vs-PDF application comparison directly from the command line."
    )
    parser.add_argument("--pdf", help="Path to a single release notes PDF file.")
    parser.add_argument("--folder", help="Base folder containing release notes PDF files.")
    parser.add_argument("--excel", required=True, help="Path to the Jira Excel workbook.")
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.75,
        help="Fuzzy similarity threshold used when the app name in Excel is not an exact match. Default: 0.75.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output filepath where the Markdown report should be saved.",
    )
    return parser


def sanitize_cell(value):
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    return text.strip()


def to_markdown_table(headers, rows):
    if not rows:
        return "No rows to show."

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for row in rows:
        values = [sanitize_cell(row.get(header, "")) for header in headers]
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines)


def discover_pdf_files(base_folder):
    pdf_paths = []
    for root_dir, dirs, files in os.walk(base_folder):
        dirs[:] = [d for d in dirs if d.lower() != 'common']
        for file_name in files:
            path = os.path.join(root_dir, file_name)
            if file_name.lower().endswith(".pdf") and "release notes" in file_name.lower():
                pdf_paths.append(path)
    return sorted(pdf_paths)


def validate_paths(pdf_path: str, excel_path: str):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")


def build_report_text(result):
    comparison_rows = result.get("comparison", [])
    diff_rows = [row for row in comparison_rows if row.get("Status") != "PASS"]

    full_table = to_markdown_table(FULL_TABLE_HEADERS, comparison_rows)
    diff_table = to_markdown_table(DIFF_TABLE_HEADERS, diff_rows)

    summary_lines = [
        "### Excel vs PDF Comparison Report",
        "",
        f"- Application: {result.get('application', 'Unknown')}",
        f"- Rows in Excel: {result.get('total_excel_records', 0)}",
        f"- Rows in PDF: {result.get('total_pdf_records', 0)}",
        f"- Matched Rows: {result.get('matched_records', 0)}",
        f"- Failed Rows: {result.get('failed_records', 0)}",
        f"- Missing in PDF: {result.get('missing_in_pdf', 0)}",
        f"- Missing in Excel: {result.get('missing_in_excel', 0)}",
        f"- Overall Status: {result.get('overall_status', 'UNKNOWN')}",
        "",
        "#### Full Comparison Table",
        "",
        full_table,
        "",
        "#### Differences Only",
        "",
        diff_table,
    ]
    return "\n".join(summary_lines)


def run_single_comparison(pdf_path, excel_path, fuzzy_threshold):
    validator = JiraExcelValidator()
    result = validator.validate(
        pdf_path,
        excel_path,
        fuzzy_threshold=fuzzy_threshold,
    )
    if "error" in result:
        return None, result["error"]
    return result, None


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.pdf and not args.folder:
        parser.error("Provide either --pdf for a single PDF file or --folder for a base folder containing release notes PDFs.")

    if args.pdf and args.folder:
        parser.error("Provide only one of --pdf or --folder, not both.")

    excel_path = os.path.abspath(args.excel)
    if not os.path.exists(excel_path):
        print(f"Error: Excel file not found: {excel_path}", file=sys.stderr)
        return 1

    output_text = []
    output_bundle = []

    if args.pdf:
        pdf_path = os.path.abspath(args.pdf)
        try:
            validate_paths(pdf_path, excel_path)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        pdf_paths = [pdf_path]
    else:
        folder = os.path.abspath(args.folder)
        if not os.path.isdir(folder):
            print(f"Error: Folder not found: {folder}", file=sys.stderr)
            return 1
        pdf_paths = discover_pdf_files(folder)
        if not pdf_paths:
            print(f"Error: No release note PDF files were found under folder: {folder}", file=sys.stderr)
            return 1

    for pdf_path in pdf_paths:
        result, error = run_single_comparison(pdf_path, excel_path, args.fuzzy_threshold)
        if error:
            output_text.append(f"### {os.path.basename(pdf_path)}\n\n{error}")
            continue

        report_text = build_report_text(result)
        output_text.append(f"## {os.path.basename(pdf_path)}\n\n{report_text}")
        output_bundle.append((pdf_path, report_text))

    final_output = "\n\n".join(output_text)
    print(final_output)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final_output, encoding="utf-8")
        print(f"\nReport saved to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
