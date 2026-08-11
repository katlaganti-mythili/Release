import os
import urllib.parse
import re

class PathResolver:
    def resolve(self, pdf_path: str, link: str) -> str:
        link = urllib.parse.unquote(link)
        
        if link.lower().startswith('file://'):
            link = link[7:]
            if re.match(r'^/[a-zA-Z][:|]/', link) or re.match(r'^/[a-zA-Z][:|]\\', link):
                link = link[1:]
                if link[1] == '|':
                    link = link[0] + ':' + link[2:]
            elif not link.startswith('/') and not link.startswith('\\'):
                link = '\\\\' + link
            elif link.startswith('//'):
                link = '\\\\' + link.lstrip('/')
            elif link.startswith('/\\\\'):
                link = link[1:]
        elif link.lower().startswith('file:'):
            link = link[5:]
            
        if len(link) >= 2 and link[1] == '|':
            link = link[0] + ':' + link[2:]

        base_dir = os.path.dirname(os.path.abspath(pdf_path))
        
        if link.startswith("\\") and not link.startswith("\\\\"):
            parts = link.strip("\\").split("\\")
            if parts and ("." in parts[0] or len(parts[0]) > 1):
                link = "\\" + link
                
        if os.path.isabs(link) or link.startswith(r"\\") or link.startswith("//"):
            return os.path.normpath(link)
            
        return os.path.normpath(os.path.join(base_dir, link))

r = PathResolver()
pdf = "C:\\docs\\release.pdf"
print(r.resolve(pdf, "file:///C|/temp/doc.pdf"))
print(r.resolve(pdf, "file:///C:/temp/doc.pdf"))
print(r.resolve(pdf, "file://server/share/doc.pdf"))
print(r.resolve(pdf, "file:////server/share/doc.pdf"))
print(r.resolve(pdf, "file:///\\\\server\\share\\doc.pdf"))
print(r.resolve(pdf, "\\server\\share\\doc.pdf"))
print(r.resolve(pdf, "relative/doc.pdf"))
print(r.resolve(pdf, "file:relative/doc.pdf"))