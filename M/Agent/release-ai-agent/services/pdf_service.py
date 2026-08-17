import pdfplumber


class PDFService:

    def extract_text(self, file):

        text = ""

        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""

        return text