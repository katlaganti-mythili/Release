import os
import fitz

class PDFValidator:
    def validate(self, paths: list):
        results = []

        for path in paths:
            result = {
                "file_path": path,
                "exists": False,
                "readable": False,
                "status": "FAIL",
                "error": None
            }

            if os.path.exists(path):
                result["exists"] = True

                try:
                    doc = fitz.open(path)
                    _ = len(doc)

                    result["readable"] = True
                    result["status"] = "PASS"

                except Exception as e:
                    result["error"] = str(e)

            else:
                result["error"] = "File not found"

            results.append(result)

        return results
