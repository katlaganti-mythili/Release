from dataclasses import dataclass, field
from typing import List

@dataclass
class ReleaseState:
    pdf_path: str = ""
    text: str = ""
    raw_links: List[dict] = field(default_factory=list)
    resolved_paths: List[str] = field(default_factory=list)
    pdf_validation: List[dict] = field(default_factory=list)
    toc_validation: dict = field(default_factory=dict)
    system_determined_latest_version: str = "Unknown"
    final_report: str = ""
    report_path: str = ""
