from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class ReleaseState:
    pdf_path: str = ""
    excel_path: str = ""
    text: str = ""
    raw_links: List[dict] = field(default_factory=list) # Links as found in the PDF
    resolved_links: List[dict] = field(default_factory=list) # Links resolved to absolute paths {'original_link': str, 'resolved_path': str}
    pdf_validation: List[dict] = field(default_factory=list)
    toc_validation: dict = field(default_factory=dict)
    excel_validation: dict = field(default_factory=dict)
    system_determined_latest_version: str = "Unknown"
    final_report: str = ""
    report_path: str = ""
    root_folder: str = ""  # Root folder for batch scanning mode
    application_mapping: dict = field(default_factory=dict)  # Holds consolidated mapping results
