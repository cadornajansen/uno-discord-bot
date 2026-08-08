import asyncio
from unittest.mock import MagicMock, patch
import pytest

from bot.services.ocr import (
    OCRService,
    OCRError,
    is_supported_image,
    normalize_ocr_text,
)


def test_is_supported_image_extensions():
    """Test image extension matching for PNG, JPG, JPEG, WEBP."""
    assert is_supported_image("assignment.png") is True
    assert is_supported_image("homework.jpg") is True
    assert is_supported_image("photo.jpeg") is True
    assert is_supported_image("screen.webp") is True

    # Case insensitive
    assert is_supported_image("CAPTURE.PNG") is True
    assert is_supported_image("IMAGE.JPG") is True

    # Unsupported extensions
    assert is_supported_image("document.pdf") is False
    assert is_supported_image("archive.zip") is False
    assert is_supported_image("vector.svg") is False
    assert is_supported_image("anim.gif") is False


def test_is_supported_image_mime_types():
    """Test MIME type matching."""
    assert is_supported_image("file", "image/png") is True
    assert is_supported_image("file", "image/jpeg") is True
    assert is_supported_image("file", "image/webp") is True
    assert is_supported_image("file", "application/pdf") is False


def test_normalize_ocr_text():
    """Test whitespace stripping, newline collapsing, and length thresholding."""
    raw = "  Line 1  \n\n\n\n  Line 2  \n  Line 3  "
    norm = normalize_ocr_text(raw, min_chars=10)
    assert norm == "Line 1\n\nLine 2\nLine 3"

    # Below min_chars returns empty string
    short_raw = "  OK  "
    assert normalize_ocr_text(short_raw, min_chars=10) == ""


def test_ocr_service_successful_extraction():
    """Test OCRService extracts text from engine output."""
    async def _test():
        service = OCRService(min_text_chars=10)

        # Mock engine output: (result, elapse)
        mock_result = [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], "Homework Assignment #1", 0.95],
            [[[0, 20], [10, 20], [10, 30], [0, 30]], "Due Date: August 15", 0.90],
        ]

        with patch.object(service, "_get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.return_value = (mock_result, 0.1)
            mock_get_engine.return_value = mock_engine

            extracted = await service.extract_text(b"fake_image_bytes")

            assert "Homework Assignment #1" in extracted
            assert "Due Date: August 15" in extracted

    asyncio.run(_test())


def test_ocr_service_empty_result():
    """Test OCRService handles empty or None engine result safely."""
    async def _test():
        service = OCRService(min_text_chars=10)

        with patch.object(service, "_get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.return_value = (None, 0.1)
            mock_get_engine.return_value = mock_engine

            extracted = await service.extract_text(b"blank_image_bytes")
            assert extracted == ""

    asyncio.run(_test())


def test_ocr_service_below_min_chars():
    """Test OCRService returns empty string if extracted text is below min_chars."""
    async def _test():
        service = OCRService(min_text_chars=10)

        mock_result = [
            [[[0, 0], [5, 0], [5, 5], [0, 5]], "123", 0.99],
        ]

        with patch.object(service, "_get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.return_value = (mock_result, 0.1)
            mock_get_engine.return_value = mock_engine

            extracted = await service.extract_text(b"tiny_image_bytes")
            assert extracted == ""

    asyncio.run(_test())


def test_ocr_service_engine_exception_handled():
    """Test OCRService wraps engine exceptions in OCRError."""
    async def _test():
        service = OCRService(min_text_chars=10)

        with patch.object(service, "_get_engine") as mock_get_engine:
            mock_engine = MagicMock()
            mock_engine.side_effect = RuntimeError("ONNX crash")
            mock_get_engine.return_value = mock_engine

            with pytest.raises(OCRError, match="OCR inference failed"):
                await service.extract_text(b"corrupt_bytes")

    asyncio.run(_test())
