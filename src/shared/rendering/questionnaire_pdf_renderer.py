"""Structured bilingual PDF rendering for discovery questionnaires."""

from html import escape
from pathlib import Path
import re
from uuid import UUID

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


class QuestionnairePdfRenderer:
    """Turn questionnaire Markdown into a clear Arabic/English PDF."""

    _heading_pattern = re.compile(r"^#{1,3}\s*(.+)$")
    _numbered_pattern = re.compile(r"^(\d+[.)])\s*(.+)$")

    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory

    def render(self, questionnaire_run_id: UUID, content: str) -> Path:
        """Create a styled, bilingual PDF from model-generated Markdown."""
        self._output_directory.mkdir(parents=True, exist_ok=True)
        output_path = self._output_directory / f"discovery-questionnaire-{questionnaire_run_id}.pdf"
        styles = self._create_styles(self._register_font())
        story = []

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line == "---":
                story.append(Spacer(1, 0.18 * cm))
                continue

            text = self._clean_markdown(line)
            is_arabic = self._contains_arabic(text)
            heading_match = self._heading_pattern.match(line)
            numbered_match = self._numbered_pattern.match(text)
            if heading_match:
                style = styles["arabic_heading"] if is_arabic else styles["english_heading"]
            elif numbered_match:
                style = styles["arabic_question"] if is_arabic else styles["english_question"]
            else:
                style = styles["arabic_body"] if is_arabic else styles["english_body"]
            story.append(Paragraph(self._prepare_text(text, is_arabic), style))

        SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.8 * cm,
            leftMargin=1.8 * cm,
            topMargin=1.6 * cm,
            bottomMargin=1.6 * cm,
        ).build(story)
        return output_path

    @classmethod
    def _clean_markdown(cls, line: str) -> str:
        """Remove Markdown markers that should not be printed literally."""
        line = cls._heading_pattern.sub(r"\1", line)
        line = line.replace("**", "").replace("`", "")
        return line.strip("* ")

    @staticmethod
    def _contains_arabic(text: str) -> bool:
        return any("\u0600" <= character <= "\u06ff" for character in text)

    def _prepare_text(self, text: str, is_arabic: bool) -> str:
        escaped = escape(text)
        return self._shape_arabic(escaped) if is_arabic else escaped

    @staticmethod
    def _shape_arabic(text: str) -> str:
        """Apply Arabic joining and visual RTL order for ReportLab."""
        return get_display(arabic_reshaper.reshape(text))

    @staticmethod
    def _create_styles(font_name: str) -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()["BodyText"]
        return {
            "arabic_heading": ParagraphStyle(
                "arabic_heading", parent=base, fontName=font_name, fontSize=14,
                leading=21, alignment=TA_RIGHT, spaceBefore=12, spaceAfter=8,
            ),
            "english_heading": ParagraphStyle(
                "english_heading", parent=base, fontName=font_name, fontSize=14,
                leading=21, alignment=TA_LEFT, spaceBefore=12, spaceAfter=8,
            ),
            "arabic_question": ParagraphStyle(
                "arabic_question", parent=base, fontName=font_name, fontSize=10.5,
                leading=17, alignment=TA_RIGHT, spaceAfter=7,
            ),
            "english_question": ParagraphStyle(
                "english_question", parent=base, fontName=font_name, fontSize=10.5,
                leading=17, alignment=TA_LEFT, spaceAfter=7,
            ),
            "arabic_body": ParagraphStyle(
                "arabic_body", parent=base, fontName=font_name, fontSize=10,
                leading=16, alignment=TA_RIGHT, spaceAfter=6,
            ),
            "english_body": ParagraphStyle(
                "english_body", parent=base, fontName=font_name, fontSize=10,
                leading=16, alignment=TA_LEFT, spaceAfter=6,
            ),
        }

    @staticmethod
    def _register_font() -> str:
        """Use an installed Unicode font on Windows, with a safe fallback."""
        font_path = Path("C:/Windows/Fonts/arial.ttf")
        if font_path.exists() and "DatumArabic" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DatumArabic", str(font_path)))
        return "DatumArabic" if "DatumArabic" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
