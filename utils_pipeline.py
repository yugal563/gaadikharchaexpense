import os
import cv2
import numpy as np
import threading

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

def preprocess_receipt_pipeline(image_bytes: bytes) -> bytes:
    """
    Execute the full CPU-optimized preprocessing pipeline:
    1. Decode image.
    2. Detect receipt boundary and crop (YOLO ONNX, no fallback).
    3. Perform blur check (Laplacian variance).
    4. If blurry, perform super-resolution upscaling (FSRCNN, no fallback).
    5. Convert to grayscale and apply CLAHE.
    6. Denoise and apply adaptive threshold binarization for clean OCR results.
    7. Return the preprocessed JPEG bytes.
    """
    try:
        # 1. Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes
            
        # Downscale large images to speed up preprocessing
        max_dim = 1600
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            
        # 2. YOLO Crop (No fallback)
        yolo_path = os.path.join("weights", "yolov8n-document.onnx")
        yolo_fallback_path = os.path.join("weights", "yolov5n-document.onnx")
        
        cropped = img
        crop_success = False
        
        if os.path.exists(yolo_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_path)
        elif os.path.exists(yolo_fallback_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_fallback_path)
            
        # 3. Blur Check on grayscale cropped version
        gray_temp = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        is_blurry, var_score = check_is_blurry(gray_temp, threshold=100.0)
        
        # 4. Super-Resolution (if blurry, upscale the BGR image)
        if is_blurry:
            print(f"[Pipeline] Receipt classified as blurry (variance: {var_score:.2f} < 100). Upscaling...")
            cropped = upscale_image_fsrcnn(cropped, scale=2)
        else:
            print(f"[Pipeline] Receipt is clear (variance: {var_score:.2f} >= 100). Skipping upscale.")
            
        # Convert the cropped (and possibly upscaled) image to grayscale
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        
        # 5. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        if isinstance(clahe, cv2.CLAHE):
            enhanced = clahe.apply(gray)
        else:
            enhanced = cv2.equalizeHist(gray)
        
        # 6. Denoise using fastNlMeansDenoising
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=10, templateWindowSize=7, searchWindowSize=21)
        
        # 7. Skip binarization - encode enhanced/denoised grayscale image directly
        success, encoded_img = cv2.imencode('.jpg', denoised)
        if success:
            return encoded_img.tobytes()
            
    except Exception as e:
        print(f"[Pipeline] Execution error: {e}. Returning original bytes.")
        
    return image_bytes
