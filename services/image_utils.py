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
import threading

import cv2
import numpy as np
from fastapi import UploadFile
from PIL import Image

_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}

_thread_local = threading.local()


def get_thread_local_fsrcnn(model_path: str, scale: int):
    if not hasattr(_thread_local, "fsrcnn_models"):
        _thread_local.fsrcnn_models = {}
    cache_key = (model_path, scale)
    if cache_key not in _thread_local.fsrcnn_models:
        if hasattr(cv2, "dnn_superres"):
            try:
                sr = cv2.dnn_superres.DnnSuperResImpl_create()
                sr.readModel(model_path)
                sr.setModel("fsrcnn", scale)
                _thread_local.fsrcnn_models[cache_key] = sr
            except Exception as e:
                print(f"Error loading FSRCNN model in thread: {e}")
                _thread_local.fsrcnn_models[cache_key] = None
        else:
            _thread_local.fsrcnn_models[cache_key] = None
    return _thread_local.fsrcnn_models[cache_key]


def get_thread_local_yolo(model_path: str):
    if not hasattr(_thread_local, "yolo_nets"):
        _thread_local.yolo_nets = {}
    if model_path not in _thread_local.yolo_nets:
        _thread_local.yolo_nets[model_path] = cv2.dnn.readNetFromONNX(model_path)
    return _thread_local.yolo_nets[model_path]


def check_is_blurry(img_gray: np.ndarray, threshold: float = 100.0) -> tuple[bool, float]:
    """
    Calculate the Laplacian variance to check if the image is blurry.
    Returns (is_blurry, variance).
    """
    variance = cv2.Laplacian(img_gray, cv2.CV_64F).var()
    return variance < threshold, variance


def upscale_image_fsrcnn(img: np.ndarray, scale: int = 2) -> np.ndarray:
    """
    Upscale the image using FSRCNN via cv2.dnn_superres if the model is available.
    """
    model_path = os.path.join("weights", f"FSRCNN_x{scale}.pb")
    if os.path.exists(model_path):
        try:
            sr = get_thread_local_fsrcnn(model_path, scale)
            if sr is not None:
                upscaled = sr.upsample(img)
                return upscaled
            else:
                print("OpenCV dnn_superres module not available in this cv2 build.")
        except Exception as e:
            print(f"FSRCNN upscaling failed: {e}.")
    
    return img


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Order 4 points in top-left, top-right, bottom-right, bottom-left order.
    pts is shape (4, 2).
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Perform perspective transform to obtain a top-down, deskewed view.
    """
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    
    # Calculate width
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    
    # Calculate height
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]
    ], dtype="float32")
    
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def crop_receipt_yolo(image: np.ndarray, model_path: str) -> tuple[np.ndarray, bool]:
    """
    Detect the receipt bounding box using YOLO (v8 or v5) ONNX via OpenCV DNN.
    Returns the cropped receipt and a boolean indicating if detection succeeded.
    """
    try:
        net = get_thread_local_yolo(model_path)
        h, w = image.shape[:2]
        
        # YOLO input size is typically 640x640
        blob = cv2.dnn.blobFromImage(image, 1.0 / 255.0, (640, 640), swapRB=True, crop=False)
        net.setInput(blob)
        outputs = net.forward()
        
        if len(outputs.shape) == 3:
            output = outputs[0]
        else:
            output = outputs
            
        # Detect format: YOLOv8 transposes classes and boxes, shape [84, 8400]
        # YOLOv5 keeps them as [25200, 85]
        is_yolov8 = False
        if output.shape[0] < output.shape[1]:
            output = output.T
            is_yolov8 = True
            
        boxes = []
        confidences = []
        
        for row in output:
            if is_yolov8:
                classes_scores = row[4:]
                confidence = float(np.max(classes_scores))
            else:
                obj_conf = row[4]
                classes_scores = row[5:]
                confidence = float(obj_conf * np.max(classes_scores))
                
            if confidence > 0.3:
                xc, yc, w_det, h_det = row[0:4]
                x1 = int((xc - w_det / 2) * w / 640.0)
                y1 = int((yc - h_det / 2) * h / 640.0)
                width = int(w_det * w / 640.0)
                height = int(h_det * h / 640.0)
                
                boxes.append([x1, y1, width, height])
                confidences.append(confidence)
        
        if not boxes:
            return image, False
            
        indices = cv2.dnn.NMSBoxes(boxes, confidences, 0.3, 0.4)
        if len(indices) > 0:
            best_idx = indices[0]
            if isinstance(best_idx, (list, np.ndarray)):
                best_idx = best_idx[0]
            x, y, box_w, box_h = boxes[best_idx]
            
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + box_w)
            y2 = min(h, y + box_h)
            
            if (x2 - x1) > 10 and (y2 - y1) > 10:
                return image[y1:y2, x1:x2], True
    except Exception as e:
        print(f"YOLO ONNX detection failed: {e}")
        
    return image, False


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
