"""Safe, bounded text extraction for files supplied to the questionnaire."""

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


class UnsupportedDocumentError(ValueError):
    """The uploaded format is not accepted for this base implementation."""


def extract_text(filename: str, content: bytes) -> str:
    """Extract readable text from PDF, DOCX, or UTF-8 text files."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    elif suffix == ".docx":
        text = "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    elif suffix in {".txt", ".md"}:
        text = content.decode("utf-8")
    else:
        raise UnsupportedDocumentError("Only PDF, DOCX, TXT, and Markdown files are supported")
    if not text.strip():
        raise UnsupportedDocumentError("The document does not contain extractable text")
    return text.strip()
