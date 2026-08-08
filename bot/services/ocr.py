import asyncio
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp"})
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class OCRError(Exception):
    """Base exception for OCR service errors."""

    pass


def is_supported_image(filename: str, content_type: Optional[str] = None) -> bool:
    """Determine whether an attachment is a supported image type for OCR processing.

    Args:
        filename: Attachment filename (e.g. 'assignment.png').
        content_type: Optional MIME content-type header (e.g. 'image/png').

    Returns:
        True if supported; False otherwise.
    """
    if content_type and content_type.lower() in SUPPORTED_IMAGE_MIME_TYPES:
        return True

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in SUPPORTED_IMAGE_EXTENSIONS


def normalize_ocr_text(text: str, min_chars: int = 10) -> str:
    """Clean and normalize raw OCR text.

    Strips whitespace, collapses 3+ consecutive newlines to 2, and enforces a minimum character threshold.

    Args:
        text: Raw OCR text string.
        min_chars: Minimum character length required (default: 10).

    Returns:
        Normalized text string, or empty string if below min_chars.
    """
    if not text:
        return ""

    # Strip whitespace per line
    lines = [line.strip() for line in text.splitlines()]
    # Rejoin lines
    joined = "\n".join(lines)
    # Collapse 3+ consecutive newlines to 2
    collapsed = re.sub(r"\n{3,}", "\n\n", joined).strip()

    if len(collapsed) < min_chars:
        return ""

    return collapsed


class OCRService:
    """Service providing CPU-bound local OCR using RapidOCR and ONNX Runtime."""

    def __init__(self, min_text_chars: int = 10):
        self.min_text_chars = min_text_chars
        self._engine = None

    def _get_engine(self):
        """Lazy load RapidOCR engine instance once."""
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR()
            except Exception as e:
                logger.error(f"Failed to initialize RapidOCR engine: {e}")
                raise OCRError(f"RapidOCR initialization failed: {e}") from e
        return self._engine

    def _ocr_sync(self, image_bytes: bytes) -> str:
        """Synchronous CPU-bound RapidOCR inference call."""
        engine = self._get_engine()
        try:
            result, _elapse = engine(image_bytes)
            if not result:
                return ""

            lines = []
            for item in result:
                # item is [box, text, score]
                if len(item) >= 2 and item[1]:
                    txt = str(item[1]).strip()
                    if txt:
                        lines.append(txt)

            raw_text = "\n".join(lines)
            return normalize_ocr_text(raw_text, min_chars=self.min_text_chars)
        except Exception as e:
            logger.error(f"RapidOCR execution failed: {e}")
            raise OCRError(f"OCR inference failed: {e}") from e

    async def extract_text(self, image_bytes: bytes) -> str:
        """Extract normalized text from image bytes asynchronously off the main event loop.

        Args:
            image_bytes: Raw binary bytes of the image file.

        Returns:
            Normalized OCR text string, or empty string if no usable text detected.
        """
        if not image_bytes:
            return ""

        try:
            return await asyncio.to_thread(self._ocr_sync, image_bytes)
        except OCRError:
            raise
        except Exception as e:
            logger.error(f"Async OCR task error: {e}")
            raise OCRError(f"Failed to run async OCR task: {e}") from e
