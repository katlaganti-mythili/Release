class ExplainService:

    def explain_failure(self, item):

        if item.get("status") == "FAIL":

            return f"""
❌ Failure Detected: {item.get('pdf_name', 'Unknown')}

🔍 Possible Causes:
- File path incorrect or inaccessible
- Missing PDF in release package
- Version mismatch inside document
- Corrupted or unreadable file
- Network share permission issue

🛠 Suggested Fix:
- Verify file path resolution
- Ensure file exists in release package root
- Check access permissions
- Re-run validation after correction
"""

        return "✅ No issues detected"