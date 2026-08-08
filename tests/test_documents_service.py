import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from bot.services.documents import (
    DocumentService,
    DocumentAnalysis,
    UnsupportedFileError,
    DocumentParseError,
    format_markdown_table,
)


def test_unsupported_file_extension_rejected():
    """Test that unsupported file extensions (.docx, .ppt, .txt) raise UnsupportedFileError."""
    async def _test():
        service = DocumentService()
        path = Path("sample.docx")

        with pytest.raises(UnsupportedFileError, match="Unsupported file format"):
            await service.extract(path, filename="sample.docx")

    asyncio.run(_test())


def test_pdf_extraction_success():
    """Test PDF text extraction returns Markdown and DocumentAnalysis object."""
    async def _test():
        service = DocumentService()
        path = Path("lecture.pdf")

        mock_result = MagicMock()
        mock_result.markdown = "# Lecture 1\nIntroduction to Computer Science"
        mock_result.pages_needing_ocr = []

        with patch("pdf_inspector.process_pdf", return_value=mock_result) as mock_pdf:
            analysis = await service.extract(path, filename="lecture.pdf")

            mock_pdf.assert_called_once_with("lecture.pdf")
            assert analysis.file_type == "PDF"
            assert "# Lecture 1" in analysis.markdown
            assert len(analysis.warnings) == 0

    asyncio.run(_test())


def test_pdf_extraction_pages_needing_ocr_warning():
    """Test PDF extraction adds a warning when pages_needing_ocr is non-empty."""
    async def _test():
        service = DocumentService()
        path = Path("scanned.pdf")

        mock_result = MagicMock()
        mock_result.markdown = "Partial text"
        mock_result.pages_needing_ocr = [1, 3, 5]

        with patch("pdf_inspector.process_pdf", return_value=mock_result):
            analysis = await service.extract(path, filename="scanned.pdf")

            assert len(analysis.warnings) == 1
            assert "3 page(s) contain scanned or image-based content" in analysis.warnings[0]

    asyncio.run(_test())


def test_pdf_extraction_corrupt_raises_parse_error():
    """Test corrupt PDF raises DocumentParseError."""
    async def _test():
        service = DocumentService()
        path = Path("corrupt.pdf")

        with patch("pdf_inspector.process_pdf", side_effect=RuntimeError("Corrupt PDF")):
            with pytest.raises(DocumentParseError, match="Failed to process PDF"):
                await service.extract(path, filename="corrupt.pdf")

    asyncio.run(_test())


def test_pptx_extraction_success_slides_tables_notes():
    """Test PPTX extraction parses slides, tables, speaker notes, and detects visual content."""
    async def _test():
        service = DocumentService()
        path = Path("lecture.pptx")

        # Mock Slide 1
        shape_text1 = MagicMock()
        shape_text1.shape_type = 1  # Text box
        shape_text1.has_text_frame = True
        paragraph1 = MagicMock()
        paragraph1.text = "Arrays and Linked Lists"
        shape_text1.text_frame.paragraphs = [paragraph1]
        shape_text1.has_table = False

        shape_img = MagicMock()
        shape_img.shape_type = 13  # Picture
        shape_img.has_text_frame = False
        shape_img.has_table = False

        slide1 = MagicMock()
        slide1.shapes = [shape_text1, shape_img]
        slide1.has_notes_slide = True
        slide1.notes_slide.notes_text_frame.text = "Remember to explain arrays first."

        # Mock Slide 2 with Table
        shape_table = MagicMock()
        shape_table.shape_type = 19  # Table
        shape_table.has_text_frame = False
        shape_table.has_table = True

        cell1 = MagicMock()
        cell1.text = "Topic"
        cell2 = MagicMock()
        cell2.text = "Score"
        cell3 = MagicMock()
        cell3.text = "DSA"
        cell4 = MagicMock()
        cell4.text = "100"

        row1 = MagicMock()
        row1.cells = [cell1, cell2]
        row2 = MagicMock()
        row2.cells = [cell3, cell4]

        shape_table.table.rows = [row1, row2]

        slide2 = MagicMock()
        slide2.shapes = [shape_table]
        slide2.has_notes_slide = False

        mock_prs = MagicMock()
        mock_prs.slides = [slide1, slide2]

        with patch("bot.services.documents.Presentation", return_value=mock_prs):
            analysis = await service.extract(path, filename="lecture.pptx")

            assert analysis.file_type == "PPTX"
            assert analysis.slide_count == 2
            assert "# Slide 1" in analysis.markdown
            assert "Arrays and Linked Lists" in analysis.markdown
            assert "### Speaker Notes" in analysis.markdown
            assert "Remember to explain arrays first." in analysis.markdown
            assert "# Slide 2" in analysis.markdown
            assert "| Topic | Score |" in analysis.markdown
            assert "| DSA | 100 |" in analysis.markdown

            # Assert visual warning added due to shape_type == 13 (Picture)
            assert len(analysis.warnings) == 1
            assert "contains visual content" in analysis.warnings[0]

    asyncio.run(_test())


def test_character_budget_truncation_warning():
    """Test that extracted Markdown exceeding max_chars budget is truncated with warning."""
    async def _test():
        service = DocumentService(max_chars=20)
        path = Path("huge.pdf")

        mock_result = MagicMock()
        mock_result.markdown = "012345678901234567890123456789"
        mock_result.pages_needing_ocr = []

        with patch("pdf_inspector.process_pdf", return_value=mock_result):
            analysis = await service.extract(path, filename="huge.pdf")

            assert len(analysis.markdown) == 20
            assert len(analysis.warnings) == 1
            assert "exceeded the maximum character analysis limit" in analysis.warnings[0]

    asyncio.run(_test())
