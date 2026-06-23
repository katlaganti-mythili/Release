import fitz
import re


class TOCValidator:

    def _extract_visual_toc(self, doc):
        """
        Locate the Table of Contents page by text search, then extract
        kind=1 (internal page) link annotations as heading/target-page pairs.
        Deduplicates entries that share the same target page.
        """
        for i in range(min(len(doc), 15)):
            text = doc[i].get_text("text").lower()
            if "table of contents" in text or "table of content" in text:
                page = doc[i]
                entries = []
                seen_targets = set()
                for lnk in page.get_links():
                    if lnk.get("kind") != 1:
                        continue
                    target_0 = lnk.get("page")
                    if target_0 is None or target_0 in seen_targets:
                        continue
                    target_1 = target_0 + 1
                    if not (1 <= target_1 <= len(doc)):
                        continue
                    seen_targets.add(target_0)
                    # Expand the link rect to capture the full heading text on the same line
                    r = lnk["from"]
                    expanded = fitz.Rect(r[0] - 5, r[1] - 5, r[2] + 300, r[3] + 5)
                    words = page.get_text("words", clip=expanded)
                    raw = " ".join(w[4] for w in words).strip()
                    # Remove trailing underscore/dot fill and page number
                    heading = re.sub(r"[_.\s]+\d+\s*$", "", raw).strip()
                    # Remove optional leading chapter number ("1 ", "2 ", etc.)
                    heading = re.sub(r"^\d+\s+", "", heading).strip()
                    if heading:
                        entries.append((heading, target_1))
                return entries
        return []

    def _heading_on_page(self, page_text, heading):
        """Return True if the first four significant heading words appear on the page."""
        norm_h = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", heading.lower())).strip()
        norm_p = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", page_text.lower()))
        tokens = [t for t in norm_h.split() if len(t) > 1][:4]
        if not tokens:
            return False
        return " ".join(tokens) in norm_p

    def validate(self, pdf_path, latest_version=None):
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Prefer PDF metadata TOC; fall back to visual (hyperlink-based) TOC
        raw_toc = doc.get_toc()
        if raw_toc:
            toc_entries = [(h.strip(), t) for _, h, t in raw_toc if h.strip()]
            toc_source = "metadata"
        else:
            toc_entries = self._extract_visual_toc(doc)
            toc_source = "visual"

        if not toc_entries:
            return {
                "toc_structure": "INVALID",
                "toc_source": toc_source,
                "navigation_correctness": "FAIL",
                "details": (
                    "No table of contents entries found "
                    "(no PDF metadata bookmarks and no visual TOC page with internal links)."
                ),
                "total_entries": 0,
                "valid_entries": 0,
                "invalid_entries": 0,
                "entries": [],
            }

        # Determine per-section page ranges
        section_ranges = []
        for idx, (heading, target) in enumerate(toc_entries):
            end_page = toc_entries[idx + 1][1] - 1 if idx + 1 < len(toc_entries) else total_pages
            section_ranges.append((heading, target, max(target, end_page)))

        version_re = re.compile(r"\d+\.\d+\.\d+\.\d+(?:\[\d+\])?")
        date_re = re.compile(
            r"\b\d{2}[-/]\d{2}[-/]\d{4}\b|\b\d{4}[-/]\d{2}[-/]\d{2}\b"
            r"|\b[A-Za-z]{3,9}[-\s]+\d{1,2}[,\s-]*\d{4}\b",
            re.IGNORECASE,
        )

        entries = []
        valid_entries = 0

        for heading, target_page, end_page in section_ranges:
            page_in_range = 1 <= target_page <= total_pages
            navigation_ok = False
            reason = ""
            section_versions = []
            section_dates = []

            if not page_in_range:
                reason = f"Target page {target_page} is out of range (document has {total_pages} pages)."
            else:
                target_text = doc[target_page - 1].get_text("text")
                navigation_ok = self._heading_on_page(target_text, heading)
                reason = (
                    "Heading text found on target page."
                    if navigation_ok
                    else "Heading text not found on target page."
                )
                # Collect versions and dates from every page in this section
                for p in range(target_page - 1, min(end_page, total_pages)):
                    page_text = doc[p].get_text("text")
                    # Collect all versions
                    section_versions.extend(version_re.findall(page_text))
                    
                    if latest_version:
                        base_match = re.search(r"(\d+(?:\.\d+)+(?:\[\d+\])?)", latest_version)
                        base_version = base_match.group(1) if base_match else latest_version

                        if base_version.lower() in page_text.lower():
                            section_versions.append(latest_version)

                        lines = page_text.split('\n')
                        for i, line in enumerate(lines):
                            line_lower = line.lower()
                            # Only extract dates if they are near the latest version OR near date labels
                            if (base_version.lower() in line_lower) or ("release date" in line_lower) or ("date:" in line_lower) or ("product release notes" in line_lower):
                                block = "\n".join(lines[max(0, i-1):i+3])
                                section_dates.extend(date_re.findall(block))
                    else:
                        section_dates.extend(date_re.findall(page_text))

            if navigation_ok:
                valid_entries += 1

            entries.append({
                "heading": heading,
                "page": target_page,
                "status": "PASS" if navigation_ok else "FAIL",
                "details": reason,
                "versions_found": sorted(set(section_versions)),
                "dates_found": sorted(set(section_dates)),
            })

        invalid_entries = len(entries) - valid_entries
        return {
            "toc_structure": "VALID",
            "toc_source": toc_source,
            "navigation_correctness": "PASS" if invalid_entries == 0 else "FAIL",
            "details": (
                f"Validated {len(entries)} TOC entries ({toc_source} TOC); "
                f"{valid_entries} passed navigation check, {invalid_entries} failed."
            ),
            "total_entries": len(entries),
            "valid_entries": valid_entries,
            "invalid_entries": invalid_entries,
            "entries": entries,
        }