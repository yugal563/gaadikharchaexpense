"""
services/image_utils.py — Image preprocessing and format utilities.

Provides:
    - normalize_content_type()       — Normalize MIME type from filename extension
    - convert_to_jpeg_if_needed()    — Convert unsupported formats to JPEG
    - run_image_quality_check()      — Blur detection + FSRCNN upscaling
    - preprocess_image_with_opencv() — Full YOLO/contour crop + CLAHE + denoise pipeline
"""

import io
import os

import cv2
import numpy as np
from fastapi import UploadFile
from PIL import Image

from utils_pipeline import (
    crop_receipt_yolo,
    check_is_blurry,
    upscale_image_fsrcnn,
)

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


def run_image_quality_check(image_bytes: bytes, content_type: str) -> bytes:
    """
    Perform blur detection using Laplacian variance.
    If the image is blurry, upscale it using FSRCNN to improve extraction accuracy,
    while maintaining color/structure for the LLM.
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        is_blurry, var_score = check_is_blurry(gray, threshold=100.0)

        if is_blurry:
            print(f"[Pipeline] Input classified as blurry (variance: {var_score:.2f} < 100). Upscaling...")
            upscaled = upscale_image_fsrcnn(img, scale=2)
            success, encoded_img = cv2.imencode('.jpg', upscaled)
            if success:
                return encoded_img.tobytes()
        else:
            print(f"[Pipeline] Input is clear (variance: {var_score:.2f} >= 100). Skipping upscale.")
    except Exception as e:
        print(f"[Pipeline] Image quality check error: {e}. Returning original bytes.")

    return image_bytes


def preprocess_image_with_opencv(image_bytes: bytes, content_type: str) -> bytes:
    """
    If the file is an image (not a PDF), perform full preprocessing to enhance OCR legibility:
    1. Decode the image using cv2.imdecode().
    2. Crop/Deskew using YOLO Receipt Detection (no fallback).
    3. OpenCV Preprocessing (CLAHE, Denoise, Thresholding).
    4. Blur Detection (Laplacian Variance).
    5. FSRCNN Super Resolution (if blurry).
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        # 1. Decode image
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

        # 2. YOLO Crop (No fallback) (Receipt Detection & Crop/Deskew)
        yolo_path = os.path.join("weights", "yolov8n-document.onnx")
        yolo_fallback_path = os.path.join("weights", "yolov5n-document.onnx")

        cropped = img
        crop_success = False

        if os.path.exists(yolo_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_path)
        elif os.path.exists(yolo_fallback_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_fallback_path)

        # 3. Convert color to grayscale
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

        # 4. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        if isinstance(clahe, cv2.CLAHE):
            enhanced = clahe.apply(gray)
        else:
            enhanced = cv2.equalizeHist(gray)

        # 5. Denoise using fastNlMeansDenoising
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=10, templateWindowSize=7, searchWindowSize=21)

        # 6. Apply Thresholding (Binarization)
        _, thresholded = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Blending: 80% denoised grayscale + 20% binary thresholded to preserve handwritten gradients
        blended = cv2.addWeighted(denoised, 0.8, thresholded, 0.2, 0)

        # 7. Blur Detection (Laplacian Variance calculated on denoised grayscale for accuracy)
        is_blurry, var_score = check_is_blurry(denoised, threshold=100.0)

        # 8. FSRCNN Super Resolution (if blurry, upscale the blended image)
        if is_blurry:
            print(f"[Pipeline] Receipt classified as blurry (variance: {var_score:.2f} < 100). Upscaling...")
            final_img = upscale_image_fsrcnn(blended, scale=2)
        else:
            print(f"[Pipeline] Receipt is clear (variance: {var_score:.2f} >= 100). Skipping upscale.")
            final_img = blended

        # 9. Encode final binarized/upscaled image
        success, encoded_img = cv2.imencode('.jpg', final_img)
        if success:
            return encoded_img.tobytes()
    except Exception as e:
        print(f"[Pipeline] OpenCV preprocessing error: {e}. Returning original bytes.")

    return image_bytes
