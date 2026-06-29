"""
Stage 2: Image Quality check & Preprocessing
Checks and prepares image bytes for LLM processing by downscaling large files and compressing to JPEG quality 85.
"""
import cv2
import numpy as np


# Preprocessing path logic below
def run_stage2(image_bytes: bytes, content_type: str) -> bytes:
    """
    Preprocess the image bytes:
    1. Decode the image.
    2. Resize if the maximum dimension exceeds 1600 pixels.
    3. Re-encode as JPEG with quality 85 to reduce network payload.
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        # Downscale large images to speed up preprocessing and reduce network payload
        max_dim = 1600
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # Encode back to JPEG with quality 85
        success, encoded_img = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if success:
            return encoded_img.tobytes()
    except Exception as e:
        print(f"[Pipeline] Preprocessing error: {e}. Returning original bytes.")

    return image_bytes

