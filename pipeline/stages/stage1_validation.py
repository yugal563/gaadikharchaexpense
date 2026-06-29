"""
Stage 1: Validation
Validates the uploaded file MIME type to ensure it is a supported image format or PDF.
"""
import io
from fastapi import HTTPException, UploadFile
from PIL import Image

_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}


def normalize_content_type(file: UploadFile) -> str:
    """Normalize file content type based on its filename extension if possible."""
    content_type = file.content_type
    filename = file.filename
    if filename:
        fn = filename.lower()
        if fn.endswith(".pdf"):
            return "application/pdf"
        elif fn.endswith(".png"):
            return "image/png"
        elif fn.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        elif fn.endswith(".bmp"):
            return "image/bmp"
        elif fn.endswith((".tif", ".tiff")):
            return "image/tiff"
        elif fn.endswith(".webp"):
            return "image/webp"
    return content_type or "image/jpeg"


def convert_to_jpeg_if_needed(image_bytes: bytes, content_type: str) -> bytes:
    """Convert unsupported image formats to JPEG."""
    if content_type in _SUPPORTED_MIME:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


async def run_stage1(f: UploadFile) -> tuple[bytes, str]:
    """Validate uploaded file MIME type and return (image_bytes, content_type)."""
    content_type = normalize_content_type(f)
    if content_type not in _SUPPORTED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for {f.filename}.")
    image_bytes = await f.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    return image_bytes, content_type
