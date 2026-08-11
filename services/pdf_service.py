import fitz


class PDFService:

    def extract_text(self, file):

        text = ""

        with open(file, "rb") as f:
            pdf_bytes = f.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text() or ""

        return text