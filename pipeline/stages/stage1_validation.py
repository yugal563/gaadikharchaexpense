from fastapi import HTTPException, UploadFile
from pipeline.stages.stage2_preprocessing import (
    normalize_content_type,
    convert_to_jpeg_if_needed,
)

async def run_stage1(f: UploadFile) -> tuple[bytes, str]:
    """Validate uploaded file MIME type and return (image_bytes, content_type)."""
    content_type = normalize_content_type(f)
    allowed = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for {f.filename}.")
    image_bytes = await f.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    return image_bytes, content_type
