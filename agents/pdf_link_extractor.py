import fitz
import urllib.parse
import re

class PDFLinkExtractor:
    def extract_links(self, pdf_path: str):
        links = []
        seen_uris = set()
        
        def get_dedup_key(s: str) -> str:
            s = urllib.parse.unquote(s).strip().lower()
            s = re.sub(r'^file:///?', '', s)
            s = s.lstrip('/\\')
            return s

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_links = page.get_links()

                # Extract from annotations
                for link in page_links:
                    # URL or file links
                    uri = ""
                    if "uri" in link:
                        uri = link["uri"]
                    elif "file" in link:
                        uri = link["file"]
                    
                    if not uri:
                        continue
                        
                    if uri.lower().startswith("https://") or uri.lower().startswith("http://"):
                        continue
                        
                    if not uri.lower().strip().endswith(".pdf"):
                        continue

                    # Unquote URI to get the actual path with spaces instead of %20
                    uri = urllib.parse.unquote(uri)
                    
                    # Remove file:// prefix if present
                    uri = re.sub(r'^file:///?', '', uri)

                    dedup_key = get_dedup_key(uri)
                    if dedup_key not in seen_uris:
                        seen_uris.add(dedup_key)
                        links.append({
                            "page": page_index + 1,
                            "link": uri,
                            "raw_text": uri
                        })

        return links
