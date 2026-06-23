# Trigger reload - Salary Slip amount + employee_id fix
from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from db import get_connection
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import re
import io
from PIL import Image
from datetime import datetime
import os
from dotenv import load_dotenv
import cv2
import numpy as np
from utils_pipeline import (
    crop_receipt_yolo,
    crop_receipt_contour,
    check_is_blurry,
    upscale_image_fsrcnn,
)


load_dotenv(override=True)

app = FastAPI(title="Vehicle Expense Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─────────────────────────────────────────────
#  Pydantic Models
# ─────────────────────────────────────────────
class Expense(BaseModel):
    category: str
    vehicle: str | None = None
    expense_date: str
    petrol_pump: str | None = None
    location: str | None = None
    liters: float | None = None
    rate_per_liter: float | None = None
    odometer: int | None = None
    service_type: str | None = None
    vendor: str | None = None
    amount: float
    paid: bool
    registration_no: str | None = None
    challan_no: str | None = None
    challan_type: str | None = None
    violation_type: str | None = None
    issued_by: str | None = None
    due_date: str | None = None
    remarks: str | None = None
    party_type: str | None = None
    party: str | None = None
    contact: str | None = None
    expense_name: str | None = None
    
    # --- New Additional DB Fields ---
    vendor_type: str | None = None
    parking_location: str | None = None
    maintenance_item: str | None = None
    custom_maintenance_item: str | None = None
    invoice_number: str | None = None
    taxable_amount: float | None = None
    non_taxable_amount: float | None = None
    km_limit: int | None = None
    hour_limit: int | None = None
    excess_km_rate: float | None = None
    excess_hour_rate: float | None = None
    excess_km_amount: float | None = None
    excess_hour_amount: float | None = None
    driver_allowance: float | None = None
    toll_charges: float | None = None
    parking_charges: float | None = None
    other_charges: float | None = None
    tds_percentage: float | None = None
    tds_amount: float | None = None
    gst_percentage: float | None = None
    gst_amount: float | None = None
    gst_invoicing_type: str | None = None
    gst_applicable_on_parking: bool | None = None
    gst_applicable_on_toll: bool | None = None
    gst_applicable_on_other_charges: bool | None = None
    paid_to: str | None = None
    contact_number: str | None = None

    model_config = {
        "extra": "allow"
    }



# ─────────────────────────────────────────────
#  Image Format Normalizer
# ─────────────────────────────────────────────
# Supported formats: JPEG, PNG, BMP, TIFF, WebP, PDF
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
    while maintaining color/structure for Azure.
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        # Convert to grayscale for blur check
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        is_blurry, var_score = check_is_blurry(gray, threshold=100.0)

        if is_blurry:
            print(f"[Pipeline] Azure input classified as blurry (variance: {var_score:.2f} < 100). Upscaling...")
            upscaled = upscale_image_fsrcnn(img, scale=2)
            success, encoded_img = cv2.imencode('.jpg', upscaled)
            if success:
                return encoded_img.tobytes()
        else:
            print(f"[Pipeline] Azure input is clear (variance: {var_score:.2f} >= 100). Skipping upscale.")
    except Exception as e:
        print(f"[Pipeline] Image quality check error: {e}. Returning original bytes.")

    return image_bytes

def preprocess_image_with_opencv(image_bytes: bytes, content_type: str) -> bytes:
    """
    If the file is an image (not a PDF), perform full preprocessing to enhance OCR legibility:
    1. Decode the image using cv2.imdecode().
    2. Crop/Deskew using YOLO Receipt Detection (with contour fallback).
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

        # 2. YOLO Crop with Contour Fallback (Receipt Detection & Crop/Deskew)
        yolo_path = os.path.join("weights", "yolov8n-document.onnx")
        yolo_fallback_path = os.path.join("weights", "yolov5n-document.onnx")
        
        cropped = img
        crop_success = False
        
        if os.path.exists(yolo_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_path)
        elif os.path.exists(yolo_fallback_path):
            cropped, crop_success = crop_receipt_yolo(img, yolo_fallback_path)
            
        if not crop_success:
            cropped = crop_receipt_contour(img)

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


# ─────────────────────────────────────────────
#  Azure OCR Helper (Removed)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  Indian Word-to-Number Parser (Tier 0 amount)
# ─────────────────────────────────────────────
_W2N = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
    "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,
    "fourteen":14,"fifteen":15,"sixteen":16,"seventeen":17,"eighteen":18,
    "nineteen":19,"twenty":20,"thirty":30,"forty":40,"fifty":50,
    "sixty":60,"seventy":70,"eighty":80,"ninety":90,
}

def _simple_words_to_num(phrase: str) -> float:
    """Convert simple English word group to number: 'thirty five thousand' → 35000."""
    tokens = re.split(r'[\s,]+', phrase.lower().strip())
    current, result = 0, 0
    for w in tokens:
        w = w.strip('.,;')
        if not w:
            continue
        if w in _W2N:
            # Check for Indian English "nine fifty" style (single digit followed by a tens word)
            if 1 <= current <= 9 and _W2N[w] in (20, 30, 40, 50, 60, 70, 80, 90):
                current = current * 100 + _W2N[w]
            else:
                current += _W2N[w]
        elif w == 'hundred':
            current = (current or 1) * 100
        elif w in ('thousand',):
            result += (current or 1) * 1_000
            current = 0
        elif w in ('lakh', 'lac', 'lakhs', 'lacs'):
            result += (current or 1) * 1_00_000
            current = 0
        elif w == 'crore':
            result += (current or 1) * 1_00_00_000
            current = 0
    return float(result + current)

def _rupee_words_to_amount(text: str) -> float | None:
    """
    Extract amount from lines like:
      'Rupees : One Lakh Thirty Five Thousand Nine Fifty and Sixteen paise'
    Returns float or None.
    """
    # Use re.finditer to try all matches on the page, in case early matches are column labels (e.g. "Amount Rs.")
    matches = re.finditer(
        r'\b(?:rupees?|rs\b\.?|inr)\s*[:\-]?\s*([A-Za-z\s\-]+?)(?:\bpaise\b|\bonly\b|[^A-Za-z\s\-]|$)',
        text, re.IGNORECASE | re.MULTILINE
    )
    for m in matches:
        phrase = m.group(1).strip()
        full_match = m.group(0).lower()
        has_paise = 'paise' in full_match
        
        paise = 0.0
        if has_paise:
            # Split by 'and' or '&' if possible
            parts = re.split(r'\b(?:and|&)\b', phrase, flags=re.IGNORECASE)
            if len(parts) > 1:
                paise_part = parts[-1].strip()
                paise = _simple_words_to_num(paise_part) / 100
                phrase = " ".join(parts[:-1]).strip()
            else:
                # Fallback: match the last word of the phrase as paise
                pm = re.search(r'\b([a-z]+)$', phrase, re.IGNORECASE)
                if pm:
                    paise = _simple_words_to_num(pm.group(1)) / 100
                    phrase = phrase[:pm.start()].strip()
                
        # Now remove noise from the phrase
        phrase = re.sub(r'\b(only|rupees?|rs\.?)\b', ' ', phrase, flags=re.IGNORECASE)
        
        main = _simple_words_to_num(phrase)
        val = round(main + paise, 2)
        if val > 0:
            return val
    return None


# ─────────────────────────────────────────────
_COMMON_CITIES = [
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata",
    "pune", "ahmedabad", "jaipur", "lucknow", "noida", "gurugram", "gurgaon",
    "chandigarh", "bhopal", "nagpur", "indore", "surat", "vadodara", "kochi",
    "secunderabad", "navi mumbai", "thane", "ghaziabad", "dhamtari", "raipur",
    "bilaspur", "ranchi", "patna", "kanpur", "agra", "meerut", "varanasi"
]

def clean_invoice_number(inv_num: str, registration_no: str = None) -> str:
    if not inv_num:
        return ""
    inv_str = str(inv_num).strip()
    reg_clean = re.sub(r'[\s\-\./]', '', str(registration_no)).upper() if registration_no else ""
    
    parts = re.split(r'[\n\r]+', inv_str)
    cleaned_parts = []
    for p in parts:
        p_clean = p.strip()
        p_no_symbol = re.sub(r'[\s\-\./]', '', p_clean).upper()
        if reg_clean and p_no_symbol == reg_clean:
            continue
        if re.match(r'^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$', p_no_symbol):
            continue
        if p_clean:
            cleaned_parts.append(p_clean)
            
    return "\n".join(cleaned_parts).strip()


# ─────────────────────────────────────────────
#  Smart Receipt Parser
# ─────────────────────────────────────────────
def parse_receipt(text: str) -> dict:
    """Infer expense fields from raw OCR text."""
    lines     = [l.strip() for l in text.strip().split("\n") if l.strip()]
    text_low  = text.lower()

    # ── Registration Number ───────────────────
    registration_no = None
    # Indian vehicle plates: MH12AB1234 / CG-12-AP-7496 / DL 1C AB 1234 or V.NO: 6244 (4-digit parking plate)
    # Allows 1-2 starting letters (e.g. to handle OCR misreads of MH like H) and spaces/dots/hyphens/slashes as separators
    reg_m = re.search(
        r'(?:reg(?:istration)?(?:\.?\s*no\.?)?|vehicle\s*no\.?|reg\.\s*no\.?|v\.?\s*no\.?)\s*[:\-]?\s*'
        r'([A-Z]{1,2}[\-\s\./]*\d{1,2}[\-\s\./]*[A-Z]{1,3}[\-\s\./]*\d{1,4}|\d{4})',
        text, re.IGNORECASE
    )
    if not reg_m:
        # Fallback: bare plate anywhere in text
        reg_m = re.search(
            r'\b([A-Z]{1,2}[\-\s\./]*\d{1,2}[\-\s\./]*[A-Z]{1,3}[\-\s\./]*\d{1,4})\b',
            text, re.IGNORECASE
        )
    if reg_m:
        registration_no = re.sub(r'[\s\-\./]', '', reg_m.group(1).upper())

    # ── Odometer / Mileage ────────────────────
    odometer = None
    odo_m = re.search(
        r'(?:mileage|odometer|km\s*reading|current\s*km|kms?)\s*[:\-]?\s*([\d,]+)',
        text_low
    )
    if odo_m:
        try:
            odometer = int(odo_m.group(1).replace(",", ""))
        except ValueError:
            pass

    # ── Category ──────────────────────────────
    # NOTE: Check absolute fuel brands first to prevent generic words like "service" (e.g. "FREM AUTO SERVICE")
    # from falsely classifying fuel receipts as Maintenance.
    category = "Other"

    absolute_fuel_brands = [
        "indian oil", "indianoil", "iocl", "hpcl", "bpcl", "bharat petroleum",
        "hindustan petroleum", "nayara", "petrol pump", "fuel station", "filling station"
    ]
    maintenance_keywords = [
        "service", "repair", "maintenance", "oil change", "tyre", "tire",
        "battery", "workshop", "garage", "mechanic", "spare", "parts",
        "lubrication", "coolant", "brake", "clutch", "filter", "alignment",
        "suspension", "exhaust", "radiator", "wiper", "bulb", "headlight",
        "body work", "denting", "painting", "washing", "servicing", "overhaul",
        "tune up", "tune-up", "engine oil", "gear oil", "transmission",
    ]
    fuel_keywords = [
        "petrol pump", "fuel station", "filling station",
        "petrol", "diesel", "hsd", "ms fuel",
        "hpcl", "iocl", "bpcl", "indian oil", "bharat petroleum",
        "hindustan petroleum", "essar", "nayara", "reliance petroleum",
    ]
    challan_keywords = [
        "parking", "challan", "toll", "traffic fine", "violation"
    ]

    if any(k in text_low for k in absolute_fuel_brands):
        category = "Fuel"
    elif any(k in text_low for k in maintenance_keywords):
        category = "Maintenance"
    elif any(k in text_low for k in fuel_keywords):
        category = "Fuel"
    elif any(k in text_low for k in challan_keywords):
        category = "Vehicle"

    # ── Amount ────────────────────────────────
    # Strategy: use a priority hierarchy so "Net Bill Amount" always beats "Sub Total".
    #   Tier 1 – Most specific final-amount keywords (net bill, grand total, net payable…)
    #   Tier 2 – Generic total keywords (total, sub total, bill amount…)
    #   Tier 3 – Largest standalone currency amount on the page (fallback)

    def _extract_amounts(pattern: str) -> list[float]:
        results = []
        for m in re.findall(pattern, text_low):
            try:
                v = float(m.replace(",", ""))
                if v > 0:
                    results.append(v)
            except ValueError:
                pass
        return results

    amount = 0.0
    amount_confidence = "low"

    # Tier 0: "Rupees: One Lakh Thirty Five Thousand..." — most reliable on formal invoices
    word_amount = _rupee_words_to_amount(text)
    if word_amount and word_amount >= 10:
        amount = word_amount
        amount_confidence = "high"

    # Tier 1: definitive "final amount" labels — allow optional (parenthetical) between label and number
    if not amount:
        tier1 = _extract_amounts(
            r'(?:net\s*bill\s*amount|net\s*bill|grand\s*total|net\s*payable|'
            r'amount\s*payable|total\s*payable|net\s*amount|amount\s*due|'
            r'invoice\s*total|total\s*due|rounded\s*amount|payable\s*amount|'
            r'total\s*charges?\s*(?:of\s*(?:repair|maintenance|service))?)'  # catches "Total Charges of Repair..."
            r'(?:\s*\([^)]*\))?'
            r'\s*[:\-]?\s*(?:rs\.?|\u20b9|inr)?\s*([\d,]+(?:\.\d{1,2})?)'
        )
        if tier1:
            amount = tier1[-1]
            amount_confidence = "high"

    # Tier 2: fuel pump receipts use "sale" / "preset"; service bills use "total" / "bill amount"
    if not amount:
        # 1. Label followed by number (same line)
        t2_a = _extract_amounts(
            r'(?:sale|total\s*amount|bill\s*amount|amount\s*paid|sub\s*total|total\s*charges?|total|amount|amt)'
            r'(?:\s*\([^)]*\))?'
            r'\s*[:\-]?\s*(?:rs\.?|\u20b9|inr)?\s*([\d,]+(?:\.\d{1,2})?)'
        )
        # 2. Number followed by total label (for columnar/tabular layout)
        t2_b = _extract_amounts(
            r'\b([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|₹|inr)?\s*[\:\-]?\s*\n?\s*'
            r'\b(?:total|g\.\s*total|gtotal|grand\s*total|net\s*payable|sub\s*total|net\s*bill|amount\s*due|invoice\s*total)\b'
        )
        # 3. "TOTAL" appears inline with the amount anywhere on the same line (e.g. "TOTAL  3343")
        t2_c = _extract_amounts(
            r'\btotal\b[^\n]{0,30}?([\d,]+(?:\.\d{1,2})?)'
        )
        tier2 = t2_a + t2_b + t2_c
        # Cap at 10 million to prevent phone numbers (10-digit) from dominating
        tier2 = [v for v in tier2 if v <= 10_000_000]
        if tier2:
            amount = max(tier2)
            amount_confidence = "high"

    # Tier 2.5: Multi-line TOTAL scanner — handles handwritten receipts where the
    # total label and value appear on separate lines (e.g. "TOTAL\nThank you!\n3343")
    if not amount:
        total_kw = re.compile(
            r'^\s*(?:grand\s*total|net\s*payable|total\s*amount|total\s*charges?|total|amount\s*due|net\s*bill)\s*[:\-]?\s*$',
            re.IGNORECASE
        )
        for idx, line in enumerate(lines):
            if total_kw.match(line):
                # Search the next 6 lines for the first plausible number
                # (handwritten receipts may have several non-numeric lines between TOTAL and the value)
                for next_line in lines[idx + 1: idx + 7]:
                    nums_in_line = re.findall(r'\b(\d{2,6}(?:\.\d{1,2})?)\b', next_line)
                    for raw_n in nums_in_line:
                        try:
                            v = float(raw_n.replace(',', ''))
                            if 10 <= v <= 9_999_999:
                                amount = v
                                amount_confidence = "high"
                                break
                        except ValueError:
                            pass
                    if amount:
                        break
            if amount:
                break

    # Tier 3a: ₹/Rs-prefixed amounts — reliable even on fuel pump receipts
    if not amount:
        rs_amounts  = _extract_amounts(r'(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d{1,2})?)')
        rs_amounts += _extract_amounts(r'([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|₹|inr)')
        plausible = [v for v in rs_amounts if 10 <= v <= 9_999_999]
        if plausible:
            amount = max(plausible)
            amount_confidence = "high"

    # Tier 3b: bare Indian-format numbers as absolute last resort (can misfire on bill/txn nos.)
    if not amount:
        # Gather all numbers on the page (for phone/PIN filtering and sum relationship check)
        all_matches = re.findall(r'\b\d+(?:,\d+)*(?:\.\d+)?\b', text)
        all_nums = []
        for m in all_matches:
            try:
                v = float(m.replace(",", ""))
                if v > 0:
                    all_nums.append(v)
            except ValueError:
                pass
        all_nums = sorted(list(set(all_nums)))

        # Gather split phone number words to ignore them
        phone_words = set()
        for p_match in re.finditer(r'\b\d{4,5}[\s\-–]?\d{5}\b', text):
            for part in re.split(r'[\s\-–]+', p_match.group(0)):
                if len(part) >= 4:
                    phone_words.add(float(part))
        for label_match in re.finditer(r'\b(?:mob(?:ile)?|tel|phone|contact|ph)\b[\s\.:\-]*(\d+)', text_low):
            phone_words.add(float(label_match.group(1)))

        # Extract bare numbers
        bare = _extract_amounts(
            r'(?<![\d:\-/])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{4,6}(?:\.\d{1,2})?)(?!\d)'
        )
        bare_nums = []
        for v in bare:
            # Ignore phone words
            if v in phone_words:
                continue
            # Ignore PIN codes (6-digit integers)
            if 100000 <= v <= 999999 and v == int(v):
                continue
            # Ignore registration number numeric parts (e.g. if MH46BB3557 is the plate, ignore 3557 and 46)
            if registration_no:
                reg_digits = re.findall(r'\d+', registration_no)
                if any(v == float(d) for d in reg_digits):
                    continue
            # Ignore odometer reading if parsed
            if odometer and v == float(odometer):
                continue
            # Plausible bare numbers for expense are between 10 and 99,999 (limits PINs and phone chunks)
            if 10 <= v <= 99999:
                bare_nums.append(v)
        bare_nums = sorted(list(set(bare_nums)))

        # Check for sum relationship (subset sum pair or triplet)
        sum_matched = None
        candidates = [n for n in all_nums if 10 <= n <= 99999]
        candidates.sort(reverse=True)
        for i, target in enumerate(candidates):
            if target not in bare_nums:
                continue
            for j in range(i + 1, len(candidates)):
                for k in range(j, len(candidates)):
                    if candidates[j] == target or candidates[k] == target:
                        continue
                    if abs(candidates[j] + candidates[k] - target) < 0.01:
                        sum_matched = target
                        break
                if sum_matched:
                    break
            if sum_matched:
                break
                
        if sum_matched:
            amount = sum_matched
            amount_confidence = "high"
        elif bare_nums:
            amount = max(bare_nums)
            amount_confidence = "low"

    amount = round(amount, 2)

    # ── Date ──────────────────────────────────
    expense_date = datetime.now().strftime("%Y-%m-%d")
    date_confidence = "low"
    
    # 1. Try numeric date formats
    date_re = [
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', "%d/%m/%Y"),
        (r'\b(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})\b', "%Y/%m/%d"),
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2})\b',  "%d/%m/%y"),
    ]
    date_found = False
    for pat, _ in date_re:
        m = re.search(pat, text)
        if m:
            raw = m.group(0).replace("-", "/").replace(".", "/")
            for fmt in ["%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y"]:
                try:
                    expense_date = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    date_confidence = "high"
                    date_found = True
                    break
                except ValueError:
                    pass
            if date_found:
                break

    # 2. Try textual month formats (e.g. 25-Jul-2009, 25 July 2009, July 25, 2009)
    if not date_found:
        months_pat = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        month_map = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
            "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
            "nov": 11, "november": 11, "dec": 12, "december": 12
        }
        # Pattern A: "25 Jul 2009" / "25-Jul-2009"
        m_a = re.search(r'\b(\d{1,2})[\s\-\./,]+(' + months_pat + r')[\s\-\./,]+(\d{2,4})\b', text, re.IGNORECASE)
        if m_a:
            try:
                day = int(m_a.group(1))
                m_str = m_a.group(2).lower()
                y_str = m_a.group(3)
                year = 2000 + int(y_str) if len(y_str) == 2 else int(y_str)
                month = month_map.get(m_str, 1)
                expense_date = datetime(year, month, day).strftime("%Y-%m-%d")
                date_confidence = "high"
                date_found = True
            except ValueError:
                pass
        
        # Pattern B: "Jul 25, 2009"
        if not date_found:
            m_b = re.search(r'\b(' + months_pat + r')[\s\-\./,]+(\d{1,2})[\s\-\./,]+(\d{2,4})\b', text, re.IGNORECASE)
            if m_b:
                try:
                    m_str = m_b.group(1).lower()
                    day = int(m_b.group(2))
                    y_str = m_b.group(3)
                    year = 2000 + int(y_str) if len(y_str) == 2 else int(y_str)
                    month = month_map.get(m_str, 1)
                    expense_date = datetime(year, month, day).strftime("%Y-%m-%d")
                    date_confidence = "high"
                    date_found = True
                except ValueError:
                    pass

    # ── Fuel-specific fields ───────────────────
    liters         = None
    rate_per_liter = None
    petrol_pump    = None

    if category == "Fuel":
        # Volume: "10.33L" / "Volume : 10.33 L" / "Volume(Ltr.): 39.33"
        lm = re.search(
            r'(?:volume|vol|qty)\s*(?:\([^)]*\))?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*(?:l\b|litre|liter|ltrs?)',
            text_low
        )
        if not lm:
            # Handle "Volume(Ltr.): 39.33" — unit BEFORE number
            lm = re.search(
                r'(?:volume|vol|qty)\s*(?:\([^)]*\))?\s*[:\-]?\s*([\d]+(?:\.\d+)?)',
                text_low
            )
        if lm:
            try: liters = float(lm.group(1))
            except ValueError: pass

        # Rate per litre — handles "Rate/Ltr.: 90.34", "Rate/Ltr .: 90.34", "Rate: 90.34"
        rm = re.search(
            r'(?:rate|price)\s*(?:/\s*ltr?\b\.?|/\s*l\b|/\s*litre|/\s*liter)?\s*(?:\.\s*)?[:\-]?\s*(?:rs\.?|₹)?\s*([\d]+(?:\.\d+)?)',
            text_low
        )
        if rm:
            try: rate_per_liter = float(rm.group(1))
            except ValueError: pass

        # Petrol pump brand — ordered from most to least specific
        brand_map = [
            ("hp auto",               "HPCL"),
            ("hp gas",                "HPCL"),
            ("hpcl",                  "HPCL"),
            ("hindustan petroleum",   "HPCL"),
            ("hindustan",             "HPCL"),   # catches Devanagari transliterations
            ("indian oil",            "Indian Oil"),
            ("iocl",                  "Indian Oil"),
            ("bharat petroleum",      "BPCL"),
            ("bpcl",                  "BPCL"),
            ("nayara",                "Nayara Energy"),
            ("essar",                 "Nayara Energy"),
            ("reliance petroleum",    "Reliance"),
            ("shell",                 "Shell"),
        ]
        for keyword, label in brand_map:
            if keyword in text_low:
                petrol_pump = label
                break

    # ── Location / City ───────────────────────
    location = None
    loc_m = re.search(
        r'(?:place\s*of\s*supply|city|location|state\s*&?\s*code?|state)\s*[:\-]?\s*([A-Za-z ]{3,30})',
        text_low
    )
    if loc_m:
        location = loc_m.group(1).strip().title()
    # PIN code approach: extract city name immediately before 6-digit Indian PIN
    # e.g. "Mumbai - 400 068" → "Mumbai"
    if not location:
        pin_m = re.search(
            r',\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s*[\(\[][^)\]]*[\)\]])?\s*[-–]?\s*\d{3}\s*\d{3}\b',
            text
        )
        if pin_m:
            location = pin_m.group(1).strip().title()
    # Common cities scanning to find known Indian cities anywhere in the text (prevents OCR misread fallbacks)
    if not location:
        for city in _COMMON_CITIES:
            if re.search(r'\b' + re.escape(city) + r'\b', text_low):
                location = city.title()
                break
    if not location:
        # Fallback: extract trailing city name from address lines (e.g. "SEC 71 NOIDA")
        _NON_CITY = {
            # payment modes
            "CASH", "UPI", "CARD", "DEBIT", "CREDIT", "NEFT", "RTGS", "CHEQUE", "ONLINE",
            # fuel / generic
            "HP", "PETROL", "DIESEL", "AUTO", "CARE", "CENTER",
            # receipt types
            "RECEIPT", "INVOICE", "PHYSICAL", "ORIGINAL", "COPY", "EXIT",
            # parking / transport
            "TERMINAL", "STATION", "PARKING", "GSTIN", "CAR", "TWO", "BIKE",
        }
        for line in lines[:8]:
            city_m = re.search(r'\b([A-Z]{3,}(?:\s[A-Z]{3,})?)\s*$', line.strip())
            if city_m:
                candidate = city_m.group(1).strip()
                if candidate not in _NON_CITY:
                    location = candidate.title()
                    break
        # Second pass: try first meaningful mixed-case word from header lines
        # catches "Secunderabad Railway Station..." → extracts "Secunderabad"
        if not location:
            for line in lines[:4]:
                wm = re.match(r'^([A-Z][a-z]{3,}(?:\s[A-Z][a-z]{3,})?)', line.strip())
                if wm:
                    candidate = wm.group(1).strip()
                    skip_words = {"Powered", "Issued", "Payment", "Vehicle", "Ticket",
                                  "Grand", "Total", "Parking", "Duration", "Thank",
                                  "Next", "Shree", "Mission", "Rupees", "Welcome",
                                  "Subject", "Date", "Time", "Dear", "From"}
                    if candidate.split()[0] not in skip_words:
                        location = candidate
                        break

    # ── Service Type ──────────────────────────
    service_type = None
    svc_m = re.search(
        r'(?:service\s*type|type\s*of\s*service)\s*[:\-]?\s*([^\n]{3,60})',
        text, re.IGNORECASE
    )
    if svc_m:
        service_type = svc_m.group(1).strip()
    elif "periodic maintenance" in text_low:
        service_type = "Periodic Maintenance"
    elif "general repair" in text_low or "general service" in text_low:
        service_type = "General Service"

    # ── Vendor / Workshop ─────────────────────
    vendor = None
    vendor_confidence = "low"
    # 1. "For SKY AUTOMOBILES" pattern (ignoring client indicators like M/s)
    for_m = re.search(
        r'\bfor\s+([A-Z][A-Za-z0-9 &\.\-]{2,40})',
        text, re.IGNORECASE
    )
    if for_m:
        vendor = for_m.group(1).strip()
        vendor_confidence = "high"
    # 2. Regex-based company name detection (works even if OCR has no newlines)
    if not vendor:
        company_re = re.search(
            r'\b([A-Z][a-zA-Z]{1,30}'
            r'(?:[ \t]+[A-Z][a-zA-Z]{1,30}){0,3}'
            r'[ \t]+(?:Enterprises?|Pvt\.?|Ltd\.?|Limited|Technologies?|Services?'
            r'|Solutions?|Motors?|Automobiles?|Workshop|Garage|Industries?'
            r'|Auto|Trading|Agency|Dealer|Centre|Center|Filling|Petroleum))\b',
            text, re.IGNORECASE
        )
        if company_re:
            vendor = company_re.group(1).strip()
            vendor_confidence = "high"
    # 3. Fall back to first meaningful non-numeric line (truncated to 100 chars)
    if not vendor:
        for line in lines[:4]:
            if len(line) > 3 and not re.match(r'^[\d\W]+$', line):
                vendor = line[:100].strip()
                vendor_confidence = "low"
                break
    # 4. Last resort: extract first meaningful word cluster from raw text
    if not vendor and lines:
        words_m = re.match(r'^([A-Za-z][A-Za-z\s]{3,60}?)(?:\s+(?:GSTIN|GST|Rs|₹|\d))', text.strip())
        if words_m:
            vendor = words_m.group(1).strip()[:100]
            vendor_confidence = "low"

    # ── Invoice Number ────────────────────────
    invoice_number = None
    matches = re.finditer(
        r'\b(invoice|bill|job|inv|receipt)\b\s*(?:no\.?|num(?:ber)?|#)?[ \t]*[:\-]?[ \t]*([A-Za-z0-9\-]{3,20})\b',
        text, re.IGNORECASE
    )
    blacklist = {
        "date", "time", "cash", "memo", "null", "none", "hosted", "on", "page", 
        "tel", "phone", "contact", "mobile", "mob", "fax", "original", "copy", 
        "customer", "retail", "service", "parts", "invoice", "bill", "job", 
        "receipt", "no", "num", "number", "model", "amount", "amt", "total", 
        "sub", "tax", "gst", "vat", "sum", "rate", "qty", "price", "particulars",
        "rs", "inr"
    }
    for m in matches:
        val = m.group(2).strip()
        if val.lower() not in blacklist:
            # Avoid single character non-digit numbers
            if not val.isdigit() and len(val) < 3:
                continue
            invoice_number = val
            break
            
    if not invoice_number:
        # Fallback: search first 15 lines for a 4-to-8 digit number close to a date or alone on a line
        for line in text.split("\n")[:15]:
            if any(kw in line.lower() for kw in {"phone", "tel", "mob", "contact", "fax", "tin", "gstin"}):
                continue
            nums = re.findall(r'\b(\d{4,8})\b', line)
            for num in nums:
                if num in {"2009", "2024", "2025", "2026", "2000"}:
                    continue
                if len(num) == 6 and any(kw in line.lower() for kw in {"pin", "delhi", "road", "area", "sector", "street"}):
                    continue
                invoice_number = num
                break
            if invoice_number:
                break

    # ── Contact Number ────────────────────────
    contact_number = None
    # Match mobile numbers (10 digits starting with 6-9, optional +91 or 0 prefix)
    # or landline numbers (e.g. 022-25792196 or similar)
    phone_m = re.search(
        r'(?:mob(?:ile)?|tel|phone|ph)\s*[:\-]?\s*(?:\+?91[ \t]*)?([6-9]\d{9}|0\d{2,4}[\-\s]?\d{6,8})\b',
        text, re.IGNORECASE
    )
    if not phone_m:
        # Fallback: search for any 10-digit number starting with 6-9
        phone_m = re.search(r'\b([6-9]\d{9})\b', text)
    if phone_m:
        contact_number = re.sub(r'[\s\-]', '', phone_m.group(1))

    # ── Taxable Amount / GST ──────────────────
    taxable_amount = None
    gst_amount = None
    gst_percentage = None

    # Taxable Amount (Subtotal before tax)
    taxable_m = re.search(
        r'(?:sub\s*total|taxable\s*amt|taxable\s*amount|value\s*of\s*goods|basic\s*val|assessable\s*val)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
        text, re.IGNORECASE
    )
    if taxable_m:
        try: taxable_amount = float(taxable_m.group(1).replace(",", ""))
        except ValueError: pass

    # ── Challan & Vehicle & Other Fields ──────
    challan_no = None
    ch_m = re.search(r'challan\s*(?:no\.?|num(?:ber)?|#)?[ \t]*[:\-]?[ \t]*([A-Za-z0-9\-]{5,30})\b', text, re.IGNORECASE)
    if ch_m:
        challan_no = ch_m.group(1).strip()

    challan_type = None
    cht_m = re.search(r'challan\s*type\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if cht_m:
        challan_type = cht_m.group(1).strip()

    violation_type = None
    viol_m = re.search(r'(?:violation\s*type|violation|offence)\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if viol_m:
        violation_type = viol_m.group(1).strip()

    issued_by = None
    ib_m = re.search(r'(?:issued\s*by|authority)\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if ib_m:
        issued_by = ib_m.group(1).strip()

    due_date = None
    dd_m = re.search(r'(?:due\s*date|pay\s*by)\s*[:\-]?\s*([\d\-./]{8,10})', text, re.IGNORECASE)
    if dd_m:
        due_date = dd_m.group(1).strip()

    parking_location = None
    pl_m = re.search(r'(?:parking\s*location|parking\s*at|parking\s*place|parking\s*spot)\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if pl_m:
        parking_location = pl_m.group(1).strip()

    party_type = None
    pt_m = re.search(r'(?:party\s*type)\s*[:\-]?\s*([^\n]{3,50})', text, re.IGNORECASE)
    if pt_m:
        party_type = pt_m.group(1).strip()

    party = None
    p_m = re.search(r'\bparty\b\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if p_m:
        party = p_m.group(1).strip()

    contact = None
    c_m = re.search(r'\bcontact\b\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if c_m:
        contact = c_m.group(1).strip()

    expense_name = None
    en_m = re.search(r'(?:expense\s*name)\s*[:\-]?\s*([^\n]{3,100})', text, re.IGNORECASE)
    if en_m:
        expense_name = en_m.group(1).strip()

    toll_charges = None
    tc_m = re.search(r'(?:toll\s*charges|toll\s*amount|toll|fastag|fastag\s*deduction)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if tc_m:
        try: toll_charges = float(tc_m.group(1).replace(",", ""))
        except ValueError: pass

    parking_charges = None
    pc_m = re.search(r'(?:parking\s*charges|parking\s*fee|parking\s*rate|parking\s*amount)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if pc_m:
        try: parking_charges = float(pc_m.group(1).replace(",", ""))
        except ValueError: pass

    other_charges = None
    oc_m = re.search(r'(?:other\s*charges|other\s*amount|misc\s*charges|misc\s*amount)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if oc_m:
        try: other_charges = float(oc_m.group(1).replace(",", ""))
        except ValueError: pass

    tds_percentage = None
    tdsp_m = re.search(r'tds\s*(?:percentage|rate|%)?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
    if tdsp_m:
        try: tds_percentage = float(tdsp_m.group(1))
        except ValueError: pass

    tds_amount = None
    tdsa_m = re.search(r'(?:tds\s*amount|tds\s*amt|tds)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if tdsa_m:
        try: tds_amount = float(tdsa_m.group(1).replace(",", ""))
        except ValueError: pass

    # GST / Tax Amount
    tax_m = re.search(
        r'(?:cgst\s*amt|sgst\s*amt|igst\s*amt|total\s*tax|tax\s*amount|gst\s*amt|vat\s*amt|vat|gst)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
        text, re.IGNORECASE
    )
    if tax_m:
        try: gst_amount = float(tax_m.group(1).replace(",", ""))
        except ValueError: pass

    # GST Percentage
    pct_m = re.search(
        r'(?:gst|vat)\s*(?:percentage|rate|%)?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*%',
        text, re.IGNORECASE
    )
    if pct_m:
        try: gst_percentage = float(pct_m.group(1))
        except ValueError: pass

    # Mathematical correction for tax values
    if amount and amount > 0.0:
        if taxable_amount and not gst_amount:
            gst_amount = round(amount - taxable_amount, 2)
        elif gst_amount and not taxable_amount:
            taxable_amount = round(amount - gst_amount, 2)
        elif gst_percentage and gst_percentage > 0.0 and not taxable_amount and not gst_amount:
            taxable_amount = round(amount / (1.0 + gst_percentage / 100.0), 2)
            gst_amount = round(amount - taxable_amount, 2)

    # ── Mathematical Validation (Fuel Category) ──
    if category == "Fuel":
        # Validate rate_per_liter (should be reasonable, e.g. < 250 in India)
        if rate_per_liter and (rate_per_liter > 250.0 or rate_per_liter <= 0.0):
            rate_per_liter = None
            
        # Try to resolve missing variables mathematically
        if amount and liters and liters > 0.0 and not rate_per_liter:
            rate_per_liter = round(amount / liters, 2)
        elif amount and rate_per_liter and rate_per_liter > 0.0 and not liters:
            liters = round(amount / rate_per_liter, 2)
        elif liters and rate_per_liter and not amount:
            amount = round(liters * rate_per_liter, 2)
            amount_confidence = "high"

    res = {
        "category":        category,
        "expense_date":    expense_date,
        "amount":          round(amount, 2),
        "liters":          liters,
        "rate_per_liter":  rate_per_liter,
        "petrol_pump":     (petrol_pump or "")[:50] or None,
        "vendor":          (vendor or "")[:100] or None,
        "registration_no": (registration_no or "")[:20] or None,
        "odometer":        odometer,
        "location":        (location or "")[:100] or None,
        "service_type":    (service_type or "")[:100] or None,
        "remarks":         f"[OCR] Scanned on {datetime.now().strftime('%d %b %Y %H:%M')}",
        "paid":            True,
        "invoice_number":  invoice_number,
        "taxable_amount":  taxable_amount,
        "non_taxable_amount": None,
        "gst_percentage":  gst_percentage,
        "gst_amount":      gst_amount,
        "contact_number":  contact_number,
        "raw_text":        text,
        "challan_no":      challan_no,
        "challan_type":    challan_type,
        "violation_type":  violation_type,
        "issued_by":       issued_by,
        "due_date":        due_date,
        "parking_location": parking_location,
        "party_type":      party_type,
        "party":           party,
        "contact":         contact,
        "expense_name":    expense_name,
        "toll_charges":    toll_charges,
        "parking_charges": parking_charges,
        "other_charges":   other_charges,
        "tds_percentage":  tds_percentage,
        "tds_amount":      tds_amount,
    }

    if category == "Fuel":
        allowed_keys = {
            "category", "expense_date", "amount", "liters", "rate_per_liter",
            "petrol_pump", "vendor", "odometer", "registration_no", "location",
            "remarks", "paid", "invoice_number", "contact_number", "raw_text"
        }
    elif category == "Maintenance":
        allowed_keys = {
            "category", "expense_date", "amount", "vendor", "registration_no",
            "odometer", "location", "service_type", "remarks", "paid",
            "vendor_type", "maintenance_item", "custom_maintenance_item",
            "invoice_number", "taxable_amount", "non_taxable_amount",
            "gst_percentage", "gst_amount", "gst_invoicing_type", "paid_to",
            "contact_number", "raw_text"
        }
    elif category == "Vehicle":
        allowed_keys = {
            "category", "expense_date", "amount", "registration_no", "location",
            "remarks", "paid", "challan_no", "challan_type", "violation_type",
            "issued_by", "due_date", "parking_location", "km_limit", "hour_limit",
            "excess_km_rate", "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
            "driver_allowance", "toll_charges", "parking_charges", "other_charges",
            "gst_applicable_on_parking", "gst_applicable_on_toll",
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount",
            "tds_percentage", "tds_amount", "service_type", "invoice_number",
            "contact_number", "paid_to", "raw_text"
        }
    else: # "Other"
        allowed_keys = {
            "category", "expense_date", "amount", "registration_no", "location",
            "remarks", "paid", "party_type", "party", "contact", "expense_name",
            "invoice_number", "contact_number", "paid_to", "raw_text"
        }

    parsed = {k: v for k, v in res.items() if k in allowed_keys}
    parsed["amount_confidence"] = amount_confidence
    parsed["vendor_confidence"] = vendor_confidence
    parsed["date_confidence"] = date_confidence
    return parsed






# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────
@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# ─────────────────────────────────────────────
#  Swagger UI OpenAPI Schema Patch
# ─────────────────────────────────────────────
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Receipt Scanner API",
        version="1.0.0",
        routes=app.routes,
    )
    # Hack to force Swagger UI to display a file upload button for list[UploadFile]
    for path in openapi_schema.get("paths", {}).values():
        for method in path.values():
            if "requestBody" in method:
                content = method["requestBody"].get("content", {})
                if "multipart/form-data" in content:
                    schema = content["multipart/form-data"].get("schema", {})
                    if "$ref" in schema:
                        ref_name = schema["$ref"].split("/")[-1]
                        schema = openapi_schema["components"]["schemas"][ref_name]
                    properties = schema.get("properties", {})
                    for prop_name, prop_val in properties.items():
                        if prop_val.get("type") == "array" and prop_val.get("items", {}).get("type") == "string":
                            prop_val["items"]["format"] = "binary"
                            
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


# ── Helper for file validation and conversion ──
async def _read_and_validate_file(f: UploadFile) -> tuple[bytes, str]:
    content_type = normalize_content_type(f)
    allowed = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for {f.filename}.")
    image_bytes = await f.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    return image_bytes, content_type



# Azure Document Intelligence helper is disabled in this branch




# ── Save Expenses Helper ──────────────────────
def save_expenses_to_db(parsed_list: list[dict]) -> list[int]:
    expense_ids = []
    conn = get_connection()
    with conn.cursor() as cursor:
        sql = """
        INSERT INTO expenses
        (
            category, vehicle, expense_date, petrol_pump, location,
            liters, rate_per_liter, odometer, service_type, vendor,
            amount, paid, registration_no, challan_no, challan_type,
            violation_type, issued_by, due_date, remarks,
            party_type, party, contact, expense_name,
            vendor_type, parking_location, maintenance_item, custom_maintenance_item,
            invoice_number, taxable_amount, non_taxable_amount,
            km_limit, hour_limit, excess_km_rate, excess_hour_rate,
            excess_km_amount, excess_hour_amount, driver_allowance,
            toll_charges, parking_charges, other_charges, tds_percentage,
            tds_amount, gst_percentage, gst_amount, gst_invoicing_type,
            gst_applicable_on_parking, gst_applicable_on_toll, gst_applicable_on_other_charges,
            paid_to, contact_number
        )
        VALUES
        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        import json
        for parsed in parsed_list:
            orig_category = parsed.get("category", "Other")
            # Map dynamic/custom category to 'Other' to satisfy MySQL ENUM
            if orig_category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                db_category = "Other"
                # Store the custom fields in remarks
                custom_remarks = f"[Custom JSON]: {json.dumps(parsed)}"
                # Save category in expense_name as fallback search key
                expense_name_val = parsed.get("expense_name") or orig_category
            else:
                db_category = orig_category
                custom_remarks = parsed.get("remarks")
                expense_name_val = parsed.get("expense_name")

            cursor.execute(sql, (
                db_category,
                parsed.get("vehicle")[:50] if parsed.get("vehicle") else None,
                parsed.get("expense_date"),
                parsed.get("petrol_pump")[:100] if parsed.get("petrol_pump") else None,
                parsed.get("location")[:100] if parsed.get("location") else None,
                parsed.get("liters"),
                parsed.get("rate_per_liter"),
                parsed.get("odometer"),
                parsed.get("service_type")[:100] if parsed.get("service_type") else None,
                parsed.get("vendor")[:100] if parsed.get("vendor") else None,
                parsed.get("amount"),
                parsed.get("paid"),
                parsed.get("registration_no")[:20] if parsed.get("registration_no") else None,
                parsed.get("challan_no")[:50] if parsed.get("challan_no") else None,
                parsed.get("challan_type")[:100] if parsed.get("challan_type") else None,
                parsed.get("violation_type")[:255] if parsed.get("violation_type") else None,
                parsed.get("issued_by")[:100] if parsed.get("issued_by") else None,
                parsed.get("due_date"),
                custom_remarks,
                parsed.get("party_type")[:100] if parsed.get("party_type") else None,
                parsed.get("party")[:100] if parsed.get("party") else None,
                parsed.get("contact")[:100] if parsed.get("contact") else None,
                expense_name_val[:100] if expense_name_val else None,
                parsed.get("vendor_type")[:20] if parsed.get("vendor_type") else None,
                parsed.get("parking_location")[:100] if parsed.get("parking_location") else None,
                parsed.get("maintenance_item")[:100] if parsed.get("maintenance_item") else None,
                parsed.get("custom_maintenance_item")[:255] if parsed.get("custom_maintenance_item") else None,
                parsed.get("invoice_number")[:50] if parsed.get("invoice_number") else None,
                parsed.get("taxable_amount"),
                parsed.get("non_taxable_amount"),
                parsed.get("km_limit"),
                parsed.get("hour_limit"),
                parsed.get("excess_km_rate"),
                parsed.get("excess_hour_rate"),
                parsed.get("excess_km_amount"),
                parsed.get("excess_hour_amount"),
                parsed.get("driver_allowance"),
                parsed.get("toll_charges"),
                parsed.get("parking_charges"),
                parsed.get("other_charges"),
                parsed.get("tds_percentage"),
                parsed.get("tds_amount"),
                parsed.get("gst_percentage"),
                parsed.get("gst_amount"),
                parsed.get("gst_invoicing_type")[:50] if parsed.get("gst_invoicing_type") else None,
                parsed.get("gst_applicable_on_parking"),
                parsed.get("gst_applicable_on_toll"),
                parsed.get("gst_applicable_on_other_charges"),
                parsed.get("paid_to")[:255] if parsed.get("paid_to") else None,
                parsed.get("contact_number")[:15] if parsed.get("contact_number") else None
            ))
            expense_ids.append(cursor.lastrowid)
        conn.commit()
    conn.close()
    return expense_ids



# Azure Document Intelligence endpoint is disabled in this branch




# ── Helper for LLM Vision processing ──────────
async def _process_single_file_llm(f: UploadFile):
    image_bytes, content_type = await _read_and_validate_file(f)
    image_bytes = run_image_quality_check(image_bytes, content_type)
    from utils_llm_pipeline import process_llm_extraction
    res = await process_llm_extraction(image_bytes, content_type)
    result = res["result"]
    result["latency_seconds"] = res["latency_seconds"]
    return result


# ── Scan Receipt (LLM Vision — Two-Pass, High Accuracy) ──
@app.post("/scan-receipt-llm")
async def scan_receipt_llm(files: list[UploadFile] = File(...)):
    """
    Upload receipt images → LLM Vision extraction (two-pass) → save to MySQL → return JSON.
    
    Uses the LLM provider configured by LLM_PROVIDER in .env.
    Supports: azure_openai, openai, gemini, anthropic, groq (Llama).
    To switch models, change LLM_PROVIDER + API key in .env and restart.
    """
    try:
        parsed_list = await asyncio.gather(*[_process_single_file_llm(f) for f in files])
        expense_ids = save_expenses_to_db(parsed_list)
        return {
            "message":     f"{len(parsed_list)} Receipt(s) scanned and saved successfully (LLM Vision)!",
            "expense_ids": expense_ids,
            "extracted":   parsed_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# ── Helper for processing based on configured scanner ──
async def _process_single_file(f: UploadFile, scanner_type: str = None):
    if not scanner_type:
        scanner_type = os.getenv("SCANNER_TYPE", "llm").lower().strip()
        
    if scanner_type == "azure":
        raise HTTPException(
            status_code=400,
            detail="Azure Document Intelligence scanner is disabled in this branch."
        )
    else:
        return await _process_single_file_llm(f)


# ── Scan Receipt (Unified router for UI) ────────────────
@app.post("/scan-receipt")
async def scan_receipt(files: list[UploadFile] = File(...)):
    try:
        parsed_list = await asyncio.gather(*[_process_single_file(f) for f in files])
        expense_ids = save_expenses_to_db(parsed_list)
        return {
            "message":     f"{len(parsed_list)} Receipt(s) scanned and saved successfully!",
            "expense_ids": expense_ids,
            "extracted":   parsed_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/scan-receipt-debug")
async def scan_receipt_debug(files: list[UploadFile] = File(...)):
    try:
        parsed_list = await asyncio.gather(*[_process_single_file(f) for f in files])
        return {
            "receipts": parsed_list
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Standard CRUD ─────────────────────────────

@app.post("/expenses")
def create_expense(expense: Expense):
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            sql = """
            INSERT INTO expenses
            (
                category, vehicle, expense_date, petrol_pump, location,
                liters, rate_per_liter, odometer, service_type, vendor,
                amount, paid, registration_no, challan_no, challan_type,
                violation_type, issued_by, due_date, remarks,
                party_type, party, contact, expense_name,
                vendor_type, parking_location, maintenance_item, custom_maintenance_item,
                invoice_number, taxable_amount, non_taxable_amount,
                km_limit, hour_limit, excess_km_rate, excess_hour_rate,
                excess_km_amount, excess_hour_amount, driver_allowance,
                toll_charges, parking_charges, other_charges, tds_percentage,
                tds_amount, gst_percentage, gst_amount, gst_invoicing_type,
                gst_applicable_on_parking, gst_applicable_on_toll, gst_applicable_on_other_charges,
                paid_to, contact_number
            )
            VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
             %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            import json
            orig_category = expense.category
            expense_dict = expense.model_dump()
            if expense.model_extra:
                expense_dict.update(expense.model_extra)

            if orig_category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
                db_category = "Other"
                # Store the custom fields in remarks
                custom_remarks = f"[Custom JSON]: {json.dumps(expense_dict)}"
                # Save category in expense_name as fallback search key
                expense_name_val = expense.expense_name or orig_category
            else:
                db_category = orig_category
                custom_remarks = expense.remarks
                expense_name_val = expense.expense_name

            cursor.execute(sql, (
                db_category,
                expense.vehicle[:50] if expense.vehicle else None,
                expense.expense_date,
                expense.petrol_pump[:100] if expense.petrol_pump else None,
                expense.location[:100] if expense.location else None,
                expense.liters,
                expense.rate_per_liter,
                expense.odometer,
                expense.service_type[:100] if expense.service_type else None,
                expense.vendor[:100] if expense.vendor else None,
                expense.amount,
                expense.paid,
                expense.registration_no[:20] if expense.registration_no else None,
                expense.challan_no[:50] if expense.challan_no else None,
                expense.challan_type[:100] if expense.challan_type else None,
                expense.violation_type[:255] if expense.violation_type else None,
                expense.issued_by[:100] if expense.issued_by else None,
                expense.due_date,
                custom_remarks,
                expense.party_type[:100] if expense.party_type else None,
                expense.party[:100] if expense.party else None,
                expense.contact[:100] if expense.contact else None,
                expense_name_val[:100] if expense_name_val else None,
                expense.vendor_type[:20] if expense.vendor_type else None,
                expense.parking_location[:100] if expense.parking_location else None,
                expense.maintenance_item[:100] if expense.maintenance_item else None,
                expense.custom_maintenance_item[:255] if expense.custom_maintenance_item else None,
                expense.invoice_number[:50] if expense.invoice_number else None,
                expense.taxable_amount,
                expense.non_taxable_amount,
                expense.km_limit,
                expense.hour_limit,
                expense.excess_km_rate,
                expense.excess_hour_rate,
                expense.excess_km_amount,
                expense.excess_hour_amount,
                expense.driver_allowance,
                expense.toll_charges,
                expense.parking_charges,
                expense.other_charges,
                expense.tds_percentage,
                expense.tds_amount,
                expense.gst_percentage,
                expense.gst_amount,
                expense.gst_invoicing_type[:50] if expense.gst_invoicing_type else None,
                expense.gst_applicable_on_parking,
                expense.gst_applicable_on_toll,
                expense.gst_applicable_on_other_charges,
                expense.paid_to[:255] if expense.paid_to else None,
                expense.contact_number[:15] if expense.contact_number else None
            ))
            conn.commit()
        conn.close()
        return {"message": "Expense added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def filter_db_record_by_category(record: dict) -> dict:
    if not record:
        return record
        
    remarks = record.get("remarks")
    if remarks and isinstance(remarks, str) and remarks.startswith("[Custom JSON]:"):
        try:
            import json
            custom_data = json.loads(remarks[len("[Custom JSON]:"):].strip())
            # Merge custom fields directly
            record.update(custom_data)
            # Remove the custom json prefix from remarks key
            record["remarks"] = custom_data.get("remarks")
            # For custom categories, we don't do standard column filtering, we return it as is
            return record
        except Exception:
            pass

    category = record.get("category")
    
    # Common columns that apply to all categories
    common_keys = {
        "expense_id", "category", "vehicle", "expense_date", "amount", 
        "paid", "remarks", "location", "registration_no", "contact_number", 
        "invoice_number", "paid_to"
    }
    
    if category == "Fuel":
        category_keys = {
            "liters", "rate_per_liter", "petrol_pump", "vendor", "odometer"
        }
    elif category == "Maintenance":
        category_keys = {
            "vendor", "odometer", "service_type", "vendor_type", 
            "maintenance_item", "custom_maintenance_item", "taxable_amount", 
            "non_taxable_amount", "gst_percentage", "gst_amount", "gst_invoicing_type"
        }
    elif category == "Vehicle":
        category_keys = {
            "challan_no", "challan_type", "violation_type", "issued_by", "due_date", 
            "parking_location", "km_limit", "hour_limit", "excess_km_rate", 
            "excess_hour_rate", "excess_km_amount", "excess_hour_amount", 
            "driver_allowance", "toll_charges", "parking_charges", "other_charges", 
            "gst_applicable_on_parking", "gst_applicable_on_toll", 
            "gst_applicable_on_other_charges", "gst_percentage", "gst_amount", 
            "tds_percentage", "tds_amount", "service_type"
        }
    elif category == "Other":
        category_keys = {
            "party_type", "party", "contact", "expense_name"
        }
    else:
        # Custom category (e.g. "Salary Slip", "Hotel Bill", "Rent Receipt", …)
        # Return all fields — don't strip custom keys like employee_name, net_pay, etc.
        return record

    allowed_keys = common_keys | category_keys
    return {k: v for k, v in record.items() if k in allowed_keys}


@app.get("/expenses")
def get_expenses():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM expenses ORDER BY expense_id DESC")
        data = cursor.fetchall()
        if data and not isinstance(data[0], dict):
            columns = [col[0] for col in cursor.description]
            data = [dict(zip(columns, row)) for row in data]
        
        data = [filter_db_record_by_category(row) for row in data]
    conn.close()
    return data


@app.get("/expenses/{expense_id}")
def get_expense(expense_id: int):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM expenses WHERE expense_id=%s", (expense_id,))
        data = cursor.fetchone()
        if data and not isinstance(data, dict):
            columns = [col[0] for col in cursor.description]
            data = dict(zip(columns, data))
        
        if data:
            data = filter_db_record_by_category(data)
    conn.close()
    return data


@app.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM expenses WHERE expense_id=%s", (expense_id,))
        conn.commit()
    conn.close()
    return {"message": "Deleted successfully"}


@app.get("/expenses/category/{category}")
def get_expenses_by_category(category: str):
    conn = get_connection()
    with conn.cursor() as cursor:
        if category not in ("Fuel", "Maintenance", "Vehicle", "Other"):
            # Custom category is stored as 'Other' in the database
            cursor.execute("SELECT * FROM expenses WHERE category = 'Other'")
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            
            # Map/filter custom fields and filter by category name
            mapped_data = []
            for row in data:
                mapped_row = filter_db_record_by_category(row)
                if mapped_row.get("category") == category:
                    mapped_data.append(mapped_row)
            data = mapped_data
        elif category == "Other":
            # Return only genuine 'Other' expenses (not custom ones mapped to 'Other')
            cursor.execute("SELECT * FROM expenses WHERE category = 'Other'")
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            
            mapped_data = []
            for row in data:
                mapped_row = filter_db_record_by_category(row)
                if mapped_row.get("category") == "Other":
                    mapped_data.append(mapped_row)
            data = mapped_data
        else:
            # Standard categories
            cursor.execute("SELECT * FROM expenses WHERE category = %s", (category,))
            data = cursor.fetchall()
            if data and not isinstance(data[0], dict):
                columns = [col[0] for col in cursor.description]
                data = [dict(zip(columns, row)) for row in data]
            
            data = [filter_db_record_by_category(row) for row in data]
            
    conn.close()
    return data
