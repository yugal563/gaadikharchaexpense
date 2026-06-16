from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from db import get_connection
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import re
import base64
import io
from PIL import Image
from datetime import datetime
import os
from dotenv import load_dotenv
import cv2
import numpy as np
from utils_azure import submit_prebuilt_receipt
from utils_paddle import run_paddle_ocr
from utils_azure_openai import analyze_receipt_with_azure_openai

load_dotenv()

# ─────────────────────────────────────────────
#  Azure Computer Vision – OCR Configuration
# ─────────────────────────────────────────────
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_OCR_KEY  = os.getenv("AZURE_OCR_KEY")

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


# ─────────────────────────────────────────────
#  Image Format Normalizer
# ─────────────────────────────────────────────
# Azure Document Intelligence supports: JPEG, PNG, BMP, TIFF, PDF
# WebP and other formats must be converted first.
_AZURE_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "application/pdf"}

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
    """Convert unsupported image formats (e.g. WebP) to JPEG for Azure OCR."""
    if content_type in _AZURE_SUPPORTED_MIME:
        return image_bytes
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

def preprocess_image_with_opencv(image_bytes: bytes, content_type: str) -> bytes:
    """
    If the file is an image (not a PDF), convert to grayscale and apply
    CLAHE (Contrast Limited Adaptive Histogram Equalization) to balance lighting
    and normalize shadows, enhancing text legibility for Azure OCR.
    """
    if content_type == "application/pdf":
        return image_bytes

    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # Denoise using fastNlMeansDenoising
        denoised = cv2.fastNlMeansDenoising(enhanced, None, h=30, templateWindowSize=7, searchWindowSize=21)

        # Adaptive threshold to binarize
        thresh = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 11, 2)

        # Encode back to JPEG
        success, encoded_img = cv2.imencode('.jpg', thresh)
        if success:
            return encoded_img.tobytes()
    except Exception:
        pass  # Fallback to raw bytes in case of any OpenCV errors

    return image_bytes


# ─────────────────────────────────────────────
#  Indian Receipt Validator
# ─────────────────────────────────────────────
_INDIAN_POSITIVE = [
    # Currency
    "₹", "rs.", "rs ", "inr", "rupee", "rupees",
    # Tax / compliance
    "gstin", "gst", "cgst", "sgst", "igst", "pan",
    # Indian oil brands
    "hpcl", "iocl", "bpcl", "indian oil", "bharat petroleum",
    "hindustan petroleum", "hindustan", "nayara", "essar oil",
    # Indian states / common city names
    "maharashtra", "delhi", "karnataka", "gujarat", "rajasthan",
    "uttar pradesh", "madhya pradesh", "tamil nadu", "telangana",
    "andhra pradesh", "kerala", "punjab", "haryana", "chhattisgarh",
    "jharkhand", "odisha", "assam", "west bengal",
    "mumbai", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "lucknow",
    "noida", "gurugram", "gurgaon", "chandigarh", "bhopal",
    "nagpur", "indore", "surat", "vadodara", "kochi",
    # Common Indian receipt keywords
    "authorised signatory", "place of supply", "state & code",
    "e & o.e", "subject to", "service tax",
]

_FOREIGN_SIGNALS = [
    # US currency / measurements
    r'\$\s*\d',          # $ followed by digit
    r'\bgallons?\b',     # gallons / gallon
    r'\bgal\b',          # GAL
    r'\busd\b',          # USD
    r'\beur\b',          # EUR
    r'\bgbp\b',          # GBP
    # US phone format: (702) 761-7000
    r'\(\d{3}\)\s*\d{3}[- ]\d{4}',
    # US ZIP codes (5-digit, but guard against Indian 6-digit PINs)
    r'\b[A-Z]{2}\s+\d{5}\b',   # e.g. NV 89019
]

def assert_indian_receipt(text: str) -> None:
    """
    Raise HTTP 422 if the OCR text does not look like an Indian receipt.
    Scoring: +1 per Indian signal found, -2 per foreign signal found.
    Tolerates blurry/handwritten receipts if zero foreign signals are found.
    """
    tl = text.lower()
    
    # Calculate foreign penalty
    foreign_penalty = 0
    for pat in _FOREIGN_SIGNALS:
        if re.search(pat, tl, re.IGNORECASE):
            foreign_penalty += 2
            
    # Positive signals score
    score = sum(1 for kw in _INDIAN_POSITIVE if kw in tl)
    
    # Tolerant GSTIN: 15 alphanumeric characters starting with 2 digits (State Code)
    if re.search(r'\b\d{2}[a-z0-9]{13}\b', tl):
        score += 3
        
    # Tolerant Indian vehicle plate structure
    if re.search(r'\b[a-z]{1,2}[\-\s\./]*\d{1,2}[\-\s\./]*[a-z]{1,3}[\-\s\./]*\d{1,4}\b', tl):
        score += 3
        
    # Handwritten/English Rupee numbers words
    if _rupee_words_to_amount(text):
        score += 2
        
    final_score = score - foreign_penalty
    
    # Determine the minimum allowed threshold
    allowed_threshold = 1
    if foreign_penalty == 0:
        # If there are no strong foreign indicators, and at least some numerical digits exist, 
        # lower the threshold to 0 to prevent rejecting unclear or handwritten local receipts.
        if re.search(r'\b\d{2,6}\b', tl):
            allowed_threshold = 0

    if final_score < allowed_threshold:
        raise HTTPException(
            status_code=422,
            detail=(
                "This receipt does not appear to be from India. "
                "Only Indian receipts (with ₹ / Rs / GST / Indian brands) are supported. "
                "Please upload a valid Indian fuel, maintenance, or service receipt."
            )
        )


# ─────────────────────────────────────────────
#  Azure OCR Helper
# ─────────────────────────────────────────────
async def run_azure_ocr(image_bytes: bytes, content_type: str = "image/jpeg") -> str:
    """Submit image to Azure AI Document Intelligence Read API and poll for result."""
    analyze_url = f"{AZURE_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30"
    submit_headers = {
        "Ocp-Apim-Subscription-Key": AZURE_OCR_KEY,
        "Content-Type": "application/json",
    }
    poll_headers = {"Ocp-Apim-Subscription-Key": AZURE_OCR_KEY}

    # Encode image as base64 – Azure accepts {"base64Source": "..."} reliably
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"base64Source": b64_image}

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Submit the image
        response = await client.post(analyze_url, headers=submit_headers, json=payload)
        if response.status_code != 202:
            raise HTTPException(
                status_code=502,
                detail=f"Azure OCR submission failed ({response.status_code}): {response.text}"
            )

        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise HTTPException(status_code=502, detail="Azure did not return an Operation-Location header.")

        # 2. Poll until done (max ~20 seconds)
        for _ in range(20):
            await asyncio.sleep(1)
            poll = await client.get(operation_url, headers=poll_headers)
            result = poll.json()
            status = result.get("status", "")

            if status == "succeeded":
                analyze_result = result.get("analyzeResult", {})
                content = analyze_result.get("content", "")
                if content:
                    return content
                
                # Fallback: join lines from pages if top-level content is empty
                lines = []
                for page in analyze_result.get("pages", []):
                    for line in page.get("lines", []):
                        lines.append(line.get("content", ""))
                return "\n".join(lines)

            if status == "failed":
                raise HTTPException(status_code=502, detail="Azure OCR processing failed.")

        raise HTTPException(status_code=504, detail="Azure OCR timed out after 20 seconds.")

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
    # NOTE: Check Maintenance FIRST – its keywords are more specific to workshops.
    # Many maintenance receipts mention "shell" (engine oil brand), "litre" (oil qty),
    # or "pump" (water pump part) which would falsely trigger Fuel if checked first.
    category = "Other"

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

    if any(k in text_low for k in maintenance_keywords):
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

    # Tier 0: "Rupees: One Lakh Thirty Five Thousand..." — most reliable on formal invoices
    word_amount = _rupee_words_to_amount(text)
    if word_amount and word_amount >= 10:
        amount = word_amount

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
        elif bare_nums:
            amount = max(bare_nums)

    amount = round(amount, 2)

    # ── Date ──────────────────────────────────
    expense_date = datetime.now().strftime("%Y-%m-%d")
    date_re = [
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', "%d/%m/%Y"),
        (r'\b(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})\b', "%Y/%m/%d"),
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2})\b',  "%d/%m/%y"),
    ]
    for pat, _ in date_re:
        m = re.search(pat, text)
        if m:
            raw = m.group(0).replace("-", "/").replace(".", "/")
            for fmt in ["%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y"]:
                try:
                    expense_date = datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass
            break

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
    # 1. "For SKY AUTOMOBILES" pattern (ignoring client indicators like M/s)
    for_m = re.search(
        r'\bfor\s+([A-Z][A-Za-z0-9 &\.\-]{2,40})',
        text, re.IGNORECASE
    )
    if for_m:
        vendor = for_m.group(1).strip()
    # 2. Regex-based company name detection (works even if OCR has no newlines)
    if not vendor:
        company_re = re.search(
            r'\b([A-Z][a-zA-Z]{1,30}'
            r'(?:\s+[A-Z][a-zA-Z]{1,30}){0,3}'
            r'\s+(?:Enterprises?|Pvt\.?|Ltd\.?|Limited|Technologies?|Services?'
            r'|Solutions?|Motors?|Automobiles?|Workshop|Garage|Industries?'
            r'|Auto|Trading|Agency|Dealer|Centre|Center|Filling|Petroleum))\b',
            text, re.IGNORECASE
        )
        if company_re:
            vendor = company_re.group(1).strip()
    # 3. Fall back to first meaningful non-numeric line (truncated to 100 chars)
    if not vendor:
        for line in lines[:4]:
            if len(line) > 3 and not re.match(r'^[\d\W]+$', line):
                vendor = line[:100].strip()
                break
    # 4. Last resort: extract first meaningful word cluster from raw text
    if not vendor and lines:
        words_m = re.match(r'^([A-Za-z][A-Za-z\s]{3,60}?)(?:\s+(?:GSTIN|GST|Rs|₹|\d))', text.strip())
        if words_m:
            vendor = words_m.group(1).strip()[:100]

    return {
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
        "raw_text":        text,
    }



# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────
@app.get("/")
def home():
    return FileResponse("static/index.html")


# ── Debug: Raw OCR text (no DB save) ──────────
@app.post("/scan-receipt-debug")
async def scan_receipt_debug(file: UploadFile = File(...)):
    """Upload a receipt → Azure OCR → return raw text + parsed fields (no DB save)."""
    content_type = normalize_content_type(file)
    allowed = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload JPEG, PNG, BMP, TIFF, WebP or PDF.")
    image_bytes = await file.read()
    image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)
    
    try:
        parsed_data = await analyze_receipt_with_azure_openai(image_bytes)
        receipts = parsed_data.get("receipts", [])
        indian_receipts = [r for r in receipts if r.get("is_indian_receipt") is True]
        if not indian_receipts:
            raise HTTPException(
                status_code=422,
                detail=(
                    "This receipt does not appear to be from India. "
                    "Only Indian receipts (with ₹ / Rs / GST / Indian brands) are supported. "
                    "Please upload a valid Indian fuel, maintenance, or service receipt."
                )
            )
        for r in indian_receipts:
            r.pop("confidence", None)
            r.pop("is_indian_receipt", None)
        return {"raw_ocr_text": "[Azure OpenAI Vision Model Parsing]", "receipts": indian_receipts}

    except HTTPException as he:
        if he.status_code == 422:
            raise
        import traceback
        traceback.print_exc()
        preprocessed_bytes = preprocess_image_with_opencv(image_bytes, content_type)
        raw_text = await run_azure_ocr(preprocessed_bytes)
        parsed = parse_receipt(raw_text)
        return {"raw_ocr_text": raw_text, "receipts": [parsed]}
    except Exception as e:
        # Fallback to existing OCR + regex parsing
        import traceback
        traceback.print_exc()
        preprocessed_bytes = preprocess_image_with_opencv(image_bytes, content_type)
        raw_text = await run_azure_ocr(preprocessed_bytes)
        parsed = parse_receipt(raw_text)
        return {"raw_ocr_text": raw_text, "receipts": [parsed]}


# ── Scan Receipt ──────────────────────────────
@app.post("/scan-receipt")
async def scan_receipt(file: UploadFile = File(...)):
    """
    Upload a receipt image → Azure OCR → smart parse → save to MySQL → return JSON.
    """
    content_type = normalize_content_type(file)
    allowed = {"image/jpeg", "image/png", "image/bmp", "image/tiff", "image/webp", "application/pdf"}
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload JPEG, PNG, BMP, TIFF, WebP or PDF.")

    try:
        image_bytes = await file.read()

        # Convert WebP / unsupported formats → JPEG before sending to Azure
        image_bytes = convert_to_jpeg_if_needed(image_bytes, content_type)

        # Step 1: Try Azure OpenAI Vision Model
        try:
            parsed_data = await analyze_receipt_with_azure_openai(image_bytes)
            receipts = parsed_data.get("receipts", [])
            indian_receipts = [r for r in receipts if r.get("is_indian_receipt") is True]
            if not indian_receipts:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "This receipt does not appear to be from India. "
                        "Only Indian receipts (with ₹ / Rs / GST / Indian brands) are supported. "
                        "Please upload a valid Indian fuel, maintenance, or service receipt."
                    )
                )
            
            for idx, r in enumerate(indian_receipts):
                r["remarks"] = f"[Azure OpenAI] Scanned on {datetime.now().strftime('%d %b %Y %H:%M')}"
                if len(indian_receipts) > 1:
                    r["remarks"] += f" (Receipt {idx+1}/{len(indian_receipts)})"
                r["paid"] = r.get("paid", True)
                r["raw_text"] = r.get("raw_text", "")
                r.pop("confidence", None)
                r.pop("is_indian_receipt", None)
                
            parsed_receipts = indian_receipts

        except HTTPException as he:
            if he.status_code == 422:
                raise
            import traceback
            traceback.print_exc()
            preprocessed_bytes = preprocess_image_with_opencv(image_bytes, content_type)
            try:
                receipt_data = await submit_prebuilt_receipt(preprocessed_bytes)
            except Exception:
                receipt_data = {}
            if receipt_data.get("MerchantName") and receipt_data.get("TransactionDate") and receipt_data.get("Total"):
                # Map Azure receipt fields to our internal schema
                parsed = {
                    "category": "Fuel" if any(k in (receipt_data.get("MerchantName") or "").lower() for k in ["hpcl", "iocl", "bpcl", "indian oil", "petrol", "diesel", "fuel"]) else "Other",
                    "expense_date": receipt_data.get("TransactionDate")[:10],
                    "amount": receipt_data.get("Total", 0),
                    "liters": None,
                    "rate_per_liter": None,
                    "petrol_pump": receipt_data.get("MerchantName"),
                    "vendor": receipt_data.get("MerchantName"),
                    "registration_no": "",
                    "odometer": None,
                    "location": "",
                    "service_type": "",
                    "remarks": f"[Azure Receipt Model] Scanned on {datetime.now().strftime('%d %b %Y %H:%M')}",
                    "paid": True,
                    "raw_text": "",
                }
            else:
                # Fallback 2: Fallback to OCR + regex parsing
                # Try PaddleOCR for handwritten receipts first
                try:
                    raw_text = await run_paddle_ocr(preprocessed_bytes)
                except Exception:
                    # Fallback to Azure OCR if PaddleOCR fails
                    raw_text = await run_azure_ocr(preprocessed_bytes)
                # Reject non-Indian receipts before parsing or saving
                assert_indian_receipt(raw_text)
                parsed = parse_receipt(raw_text)
                
            parsed_receipts = [parsed]
        except Exception as e:
            # Fallback 1: Attempt Azure prebuilt-receipt model
            import traceback
            traceback.print_exc()
            preprocessed_bytes = preprocess_image_with_opencv(image_bytes, content_type)
            try:
                receipt_data = await submit_prebuilt_receipt(preprocessed_bytes)
            except Exception:
                receipt_data = {}
            if receipt_data.get("MerchantName") and receipt_data.get("TransactionDate") and receipt_data.get("Total"):
                # Map Azure receipt fields to our internal schema
                parsed = {
                    "category": "Fuel" if any(k in (receipt_data.get("MerchantName") or "").lower() for k in ["hpcl", "iocl", "bpcl", "indian oil", "petrol", "diesel", "fuel"]) else "Other",
                    "expense_date": receipt_data.get("TransactionDate")[:10],
                    "amount": receipt_data.get("Total", 0),
                    "liters": None,
                    "rate_per_liter": None,
                    "petrol_pump": receipt_data.get("MerchantName"),
                    "vendor": receipt_data.get("MerchantName"),
                    "registration_no": "",
                    "odometer": None,
                    "location": "",
                    "service_type": "",
                    "remarks": f"[Azure Receipt Model] Scanned on {datetime.now().strftime('%d %b %Y %H:%M')}",
                    "paid": True,
                    "raw_text": "",
                }
            else:
                # Fallback 2: Fallback to OCR + regex parsing
                # Try PaddleOCR for handwritten receipts first
                try:
                    raw_text = await run_paddle_ocr(preprocessed_bytes)
                except Exception:
                    # Fallback to Azure OCR if PaddleOCR fails
                    raw_text = await run_azure_ocr(preprocessed_bytes)
                # Reject non-Indian receipts before parsing or saving
                assert_indian_receipt(raw_text)
                parsed = parse_receipt(raw_text)
                
            parsed_receipts = [parsed]

        # Step 3: Save to MySQL
        expense_ids = []
        conn = get_connection()
        with conn.cursor() as cursor:
            for parsed in parsed_receipts:
                sql = """
                INSERT INTO expenses
                (category, expense_date, amount, liters, rate_per_liter,
                 petrol_pump, vendor, service_type, odometer, registration_no,
                 location, remarks, paid)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    parsed.get("category"),
                    parsed.get("expense_date"),
                    parsed.get("amount"),
                    parsed.get("liters"),
                    parsed.get("rate_per_liter"),
                    parsed.get("petrol_pump"),
                    parsed.get("vendor"),
                    parsed.get("service_type"),
                    parsed.get("odometer"),
                    parsed.get("registration_no"),
                    parsed.get("location"),
                    parsed.get("remarks"),
                    parsed.get("paid"),
                ))
                expense_ids.append(cursor.lastrowid)
            conn.commit()
        conn.close()

        return {
            "message":     "Receipt(s) scanned and saved successfully!",
            "expense_ids": expense_ids,
            "extracted":   parsed_receipts,
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
                party_type, party, contact, expense_name
            )
            VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """
            cursor.execute(sql, (
                expense.category,
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
                expense.remarks[:255] if expense.remarks else None,
                expense.party_type[:100] if expense.party_type else None,
                expense.party[:100] if expense.party else None,
                expense.contact[:100] if expense.contact else None,
                expense.expense_name[:100] if expense.expense_name else None,
            ))
            conn.commit()
        conn.close()
        return {"message": "Expense added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/expenses")
def get_expenses():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM expenses ORDER BY expense_id DESC")
        data = cursor.fetchall()
        if data and not isinstance(data[0], dict):
            columns = [col[0] for col in cursor.description]
            data = [dict(zip(columns, row)) for row in data]
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
        cursor.execute("SELECT * FROM expenses WHERE category = %s", (category,))
        data = cursor.fetchall()
        if data and not isinstance(data[0], dict):
            columns = [col[0] for col in cursor.description]
            data = [dict(zip(columns, row)) for row in data]
    conn.close()
    return data
