import os
import urllib.parse

class PathResolver:
    def resolve(self, pdf_path: str, link: str) -> str:
        """
        Combines the root path of the release document with the relative path inside the link.
        """
        link = urllib.parse.unquote(link)
        base_dir = os.path.dirname(os.path.abspath(pdf_path))
        
        # Autocorrect network links that incorrectly start with a single backslash
        if link.startswith("\\") and not link.startswith("\\\\"):
            # Check if it looks like an IP address or common network path start
            parts = link.strip("\\").split("\\")
            if parts and ("." in parts[0] or len(parts[0]) > 1):
                link = "\\" + link
                
        if os.path.isabs(link) or link.startswith(r"\\"):
            return link
            
        # Resolve the relative path against the PDF's directory
        return os.path.normpath(os.path.join(base_dir, link))