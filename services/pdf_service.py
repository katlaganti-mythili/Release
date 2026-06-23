import fitz


class PDFService:

    def extract_text(self, file):

        text = ""

        with fitz.open(file) as doc:
            for page in doc:
                text += page.get_text() or ""

        return text