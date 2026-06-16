import os
import asyncio
import cv2
import numpy as np

# Global variable to hold the initialized PaddleOCR instance
_ocr_instance = None
_ocr_init_lock = asyncio.Lock()

def _get_ocr_under_lock():
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    # Disable oneDNN/MKLDNN globally before importing paddle/paddleocr to avoid Windows PIR executor crash
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"

    print("Lazy-initializing global PaddleOCR instance...")
    try:
        from paddleocr import PaddleOCR
        _ocr_instance = PaddleOCR(lang='en', enable_mkldnn=False)
        return _ocr_instance
    except Exception as e:
        raise RuntimeError(
            "PaddleOCR or PaddlePaddle dependency is not installed or available in this environment. "
            "Please run the app within the virtual environment (.venv) or install paddlepaddle and paddleocr. "
            f"Original error: {e}"
        ) from e


async def get_ocr_instance():
    global _ocr_instance
    if _ocr_instance is None:
        async with _ocr_init_lock:
            if _ocr_instance is None:
                _ocr_instance = await asyncio.to_thread(_get_ocr_under_lock)
    return _ocr_instance


async def run_paddle_ocr(image_bytes: bytes) -> str:
    """Run local PaddleOCR on image bytes and return the extracted text."""
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image bytes using OpenCV.")
            
        ocr = await get_ocr_instance()
        
        # Run inference in a separate thread to prevent blocking FastAPI event loop
        result = await asyncio.to_thread(ocr.ocr, img)
        
        text_lines = []
        if result:
            for item in result:
                if isinstance(item, dict) and "rec_texts" in item:
                    text_lines.extend(item["rec_texts"])
                elif isinstance(item, list):
                    for line in item:
                        if isinstance(line, list) and len(line) > 1 and isinstance(line[1], (tuple, list)):
                            text_lines.append(line[1][0])
                            
        return "\n".join(text_lines)
    except Exception as e:
        raise RuntimeError(f"PaddleOCR execution failed: {e}") from e
