import fitz

class PDFLinkExtractor:
    def extract_links(self, pdf_path: str):
        doc = fitz.open(pdf_path)
        links = []

        for page_index in range(len(doc)):
            page = doc[page_index]
            page_links = page.get_links()

            for link in page_links:
                # URL or file links
                uri = ""
                if "uri" in link:
                    uri = link["uri"]
                elif "file" in link:
                    uri = link["file"]
                
                if not uri:
                    continue

                lowered = uri.lower().strip()
                # Ignore web URLs entirely, even when they end with .pdf.
                if lowered.startswith("http://") or lowered.startswith("https://"):
                    continue
                    
                # Extract only .pdf files only
                if ".pdf" not in lowered:
                    continue

                links.append({
                        "page": page_index + 1,
                        "link": uri
                    })

        return links
