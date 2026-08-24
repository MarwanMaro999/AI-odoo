"""Safe, bounded text extraction for files supplied to the questionnaire."""

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    """The uploaded format is not accepted for this base implementation."""


def extract_text(filename: str, content: bytes, max_pdf_pages: int = 100) -> str:
    """Extract readable text from PDF, DOCX, or UTF-8 text files."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > max_pdf_pages:
            raise UnsupportedDocumentError(
                f"The PDF has more than the supported {max_pdf_pages} pages"
            )
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".docx":
        text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    elif suffix in {".txt", ".md"}:
        text = content.decode("utf-8")
    else:
        raise UnsupportedDocumentError("Only PDF, DOCX, TXT, and Markdown files are supported")
    if not text.strip():
        raise UnsupportedDocumentError("The document does not contain extractable text")
    return text.strip()
