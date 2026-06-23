"""
services/ocr_parser.py — Smart OCR receipt parser using regex heuristics.

Provides:
    - parse_receipt(text)           — Main entry: infer expense fields from raw OCR text
    - clean_invoice_number()        — Strip vehicle plate numbers mixed into invoice fields
    - _rupee_words_to_amount()      — Parse Indian word-format amounts (e.g. "One Lakh Thirty Five Thousand")
    - _simple_words_to_num()        — Convert English word groups to numbers
"""

import re
from datetime import datetime


# ─────────────────────────────────────────────
#  Indian Word-to-Number Parser (Tier 0 amount)
# ─────────────────────────────────────────────
_W2N = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_COMMON_CITIES = [
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata",
    "pune", "ahmedabad", "jaipur", "lucknow", "noida", "gurugram", "gurgaon",
    "chandigarh", "bhopal", "nagpur", "indore", "surat", "vadodara", "kochi",
    "secunderabad", "navi mumbai", "thane", "ghaziabad", "dhamtari", "raipur",
    "bilaspur", "ranchi", "patna", "kanpur", "agra", "meerut", "varanasi"
]


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
            parts = re.split(r'\b(?:and|&)\b', phrase, flags=re.IGNORECASE)
            if len(parts) > 1:
                paise_part = parts[-1].strip()
                paise = _simple_words_to_num(paise_part) / 100
                phrase = " ".join(parts[:-1]).strip()
            else:
                pm = re.search(r'\b([a-z]+)$', phrase, re.IGNORECASE)
                if pm:
                    paise = _simple_words_to_num(pm.group(1)) / 100
                    phrase = phrase[:pm.start()].strip()

        phrase = re.sub(r'\b(only|rupees?|rs\.?)\b', ' ', phrase, flags=re.IGNORECASE)
        main = _simple_words_to_num(phrase)
        val = round(main + paise, 2)
        if val > 0:
            return val
    return None


def clean_invoice_number(inv_num: str, registration_no: str = None) -> str:
    """Strip vehicle registration numbers mixed into invoice number fields."""
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


def parse_receipt(text: str) -> dict:
    """Infer expense fields from raw OCR text using regex heuristics."""
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    text_low = text.lower()

    # ── Registration Number ───────────────────
    registration_no = None
    reg_m = re.search(
        r'(?:reg(?:istration)?(?:\.?\s*no\.?)?|vehicle\s*no\.?|reg\.\s*no\.?|v\.?\s*no\.?)\s*[:\-]?\s*'
        r'([A-Z]{1,2}[\-\s\./]*\d{1,2}[\-\s\./]*[A-Z]{1,3}[\-\s\./]*\d{1,4}|\d{4})',
        text, re.IGNORECASE
    )
    if not reg_m:
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
    challan_keywords = ["parking", "challan", "toll", "traffic fine", "violation"]

    if any(k in text_low for k in absolute_fuel_brands):
        category = "Fuel"
    elif any(k in text_low for k in maintenance_keywords):
        category = "Maintenance"
    elif any(k in text_low for k in fuel_keywords):
        category = "Fuel"
    elif any(k in text_low for k in challan_keywords):
        category = "Vehicle"

    # ── Amount ────────────────────────────────
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

    # Tier 0: "Rupees: One Lakh Thirty Five Thousand..."
    word_amount = _rupee_words_to_amount(text)
    if word_amount and word_amount >= 10:
        amount = word_amount
        amount_confidence = "high"

    # Tier 1: definitive final-amount labels
    if not amount:
        tier1 = _extract_amounts(
            r'(?:net\s*bill\s*amount|net\s*bill|grand\s*total|net\s*payable|'
            r'amount\s*payable|total\s*payable|net\s*amount|amount\s*due|'
            r'invoice\s*total|total\s*due|rounded\s*amount|payable\s*amount|'
            r'total\s*charges?\s*(?:of\s*(?:repair|maintenance|service))?)'
            r'(?:\s*\([^)]*\))?'
            r'\s*[:\-]?\s*(?:rs\.?|\u20b9|inr)?\s*([\d,]+(?:\.\d{1,2})?)'
        )
        if tier1:
            amount = tier1[-1]
            amount_confidence = "high"

    # Tier 2: generic totals
    if not amount:
        t2_a = _extract_amounts(
            r'(?:sale|total\s*amount|bill\s*amount|amount\s*paid|sub\s*total|total\s*charges?|total|amount|amt)'
            r'(?:\s*\([^)]*\))?'
            r'\s*[:\-]?\s*(?:rs\.?|\u20b9|inr)?\s*([\d,]+(?:\.\d{1,2})?)'
        )
        t2_b = _extract_amounts(
            r'\b([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|₹|inr)?\s*[\:\-]?\s*\n?\s*'
            r'\b(?:total|g\.\s*total|gtotal|grand\s*total|net\s*payable|sub\s*total|net\s*bill|amount\s*due|invoice\s*total)\b'
        )
        t2_c = _extract_amounts(r'\btotal\b[^\n]{0,30}?([\d,]+(?:\.\d{1,2})?)')
        tier2 = [v for v in t2_a + t2_b + t2_c if v <= 10_000_000]
        if tier2:
            amount = max(tier2)
            amount_confidence = "high"

    # Tier 2.5: Multi-line TOTAL scanner
    if not amount:
        total_kw = re.compile(
            r'^\s*(?:grand\s*total|net\s*payable|total\s*amount|total\s*charges?|total|amount\s*due|net\s*bill)\s*[:\-]?\s*$',
            re.IGNORECASE
        )
        for idx, line in enumerate(lines):
            if total_kw.match(line):
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

    # Tier 3a: ₹/Rs-prefixed amounts
    if not amount:
        rs_amounts = _extract_amounts(r'(?:rs\.?|₹|inr)\s*([\d,]+(?:\.\d{1,2})?)')
        rs_amounts += _extract_amounts(r'([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|₹|inr)')
        plausible = [v for v in rs_amounts if 10 <= v <= 9_999_999]
        if plausible:
            amount = max(plausible)
            amount_confidence = "high"

    # Tier 3b: bare numbers as last resort
    if not amount:
        all_matches = re.findall(r'\b\d+(?:,\d+)*(?:\.\d+)?\b', text)
        all_nums = sorted(list(set(
            float(m.replace(",", "")) for m in all_matches
            if float(m.replace(",", "")) > 0
        )))

        phone_words = set()
        for p_match in re.finditer(r'\b\d{4,5}[\s\-–]?\d{5}\b', text):
            for part in re.split(r'[\s\-–]+', p_match.group(0)):
                if len(part) >= 4:
                    phone_words.add(float(part))
        for label_match in re.finditer(r'\b(?:mob(?:ile)?|tel|phone|contact|ph)\b[\s\.:\-]*(\d+)', text_low):
            phone_words.add(float(label_match.group(1)))

        bare = _extract_amounts(
            r'(?<![:\-/\d])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d{4,6}(?:\.\d{1,2})?)(?!\d)'
        )
        bare_nums = []
        for v in bare:
            if v in phone_words:
                continue
            if 100000 <= v <= 999999 and v == int(v):
                continue
            if registration_no:
                reg_digits = re.findall(r'\d+', registration_no)
                if any(v == float(d) for d in reg_digits):
                    continue
            if odometer and v == float(odometer):
                continue
            if 10 <= v <= 99999:
                bare_nums.append(v)
        bare_nums = sorted(list(set(bare_nums)))

        sum_matched = None
        candidates = sorted([n for n in all_nums if 10 <= n <= 99999], reverse=True)
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

    date_re = [
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', "%d/%m/%Y"),
        (r'\b(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})\b', "%Y/%m/%d"),
        (r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2})\b', "%d/%m/%y"),
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

    if not date_found:
        months_pat = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        month_map = {
            "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
            "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
            "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
            "nov": 11, "november": 11, "dec": 12, "december": 12
        }
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
    liters = None
    rate_per_liter = None
    petrol_pump = None

    if category == "Fuel":
        lm = re.search(
            r'(?:volume|vol|qty)\s*(?:\([^)]*\))?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*(?:l\b|litre|liter|ltrs?)',
            text_low
        )
        if not lm:
            lm = re.search(
                r'(?:volume|vol|qty)\s*(?:\([^)]*\))?\s*[:\-]?\s*([\d]+(?:\.\d+)?)',
                text_low
            )
        if lm:
            try:
                liters = float(lm.group(1))
            except ValueError:
                pass

        rm = re.search(
            r'(?:rate|price)\s*(?:/\s*ltr?\b\.?|/\s*l\b|/\s*litre|/\s*liter)?\s*(?:\.\s*)?[:\-]?\s*(?:rs\.?|₹)?\s*([\d]+(?:\.\d+)?)',
            text_low
        )
        if rm:
            try:
                rate_per_liter = float(rm.group(1))
            except ValueError:
                pass

        brand_map = [
            ("hp auto", "HPCL"), ("hp gas", "HPCL"), ("hpcl", "HPCL"),
            ("hindustan petroleum", "HPCL"), ("hindustan", "HPCL"),
            ("indian oil", "Indian Oil"), ("iocl", "Indian Oil"),
            ("bharat petroleum", "BPCL"), ("bpcl", "BPCL"),
            ("nayara", "Nayara Energy"), ("essar", "Nayara Energy"),
            ("reliance petroleum", "Reliance"), ("shell", "Shell"),
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
    if not location:
        pin_m = re.search(
            r',\s*([A-Za-z][A-Za-z\s]{2,25}?)(?:\s*[\(\[][^)\]]*[\)\]])?\s*[-–]?\s*\d{3}\s*\d{3}\b',
            text
        )
        if pin_m:
            location = pin_m.group(1).strip().title()
    if not location:
        for city in _COMMON_CITIES:
            if re.search(r'\b' + re.escape(city) + r'\b', text_low):
                location = city.title()
                break
    if not location:
        _NON_CITY = {
            "CASH", "UPI", "CARD", "DEBIT", "CREDIT", "NEFT", "RTGS", "CHEQUE", "ONLINE",
            "HP", "PETROL", "DIESEL", "AUTO", "CARE", "CENTER",
            "RECEIPT", "INVOICE", "PHYSICAL", "ORIGINAL", "COPY", "EXIT",
            "TERMINAL", "STATION", "PARKING", "GSTIN", "CAR", "TWO", "BIKE",
        }
        for line in lines[:8]:
            city_m = re.search(r'\b([A-Z]{3,}(?:\s[A-Z]{3,})?)\s*$', line.strip())
            if city_m:
                candidate = city_m.group(1).strip()
                if candidate not in _NON_CITY:
                    location = candidate.title()
                    break
        if not location:
            for line in lines[:4]:
                wm = re.match(r'^([A-Z][a-z]{3,}(?:\s[A-Z][a-z]{3,})?)', line.strip())
                if wm:
                    candidate = wm.group(1).strip()
                    skip_words = {
                        "Powered", "Issued", "Payment", "Vehicle", "Ticket",
                        "Grand", "Total", "Parking", "Duration", "Thank",
                        "Next", "Shree", "Mission", "Rupees", "Welcome",
                        "Subject", "Date", "Time", "Dear", "From"
                    }
                    if candidate.split()[0] not in skip_words:
                        location = candidate
                        break

    # ── Service Type ──────────────────────────
    service_type = None
    svc_m = re.search(r'(?:service\s*type|type\s*of\s*service)\s*[:\-]?\s*([^\n]{3,60})', text, re.IGNORECASE)
    if svc_m:
        service_type = svc_m.group(1).strip()
    elif "periodic maintenance" in text_low:
        service_type = "Periodic Maintenance"
    elif "general repair" in text_low or "general service" in text_low:
        service_type = "General Service"

    # ── Vendor / Workshop ─────────────────────
    vendor = None
    vendor_confidence = "low"
    for_m = re.search(r'\bfor\s+([A-Z][A-Za-z0-9 &\.\-]{2,40})', text, re.IGNORECASE)
    if for_m:
        vendor = for_m.group(1).strip()
        vendor_confidence = "high"
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
    if not vendor:
        for line in lines[:4]:
            if len(line) > 3 and not re.match(r'^[\d\W]+$', line):
                vendor = line[:100].strip()
                vendor_confidence = "low"
                break
    if not vendor and lines:
        words_m = re.match(r'^([A-Za-z][A-Za-z\s]{3,60}?)(?:\s+(?:GSTIN|GST|Rs|₹|\d))', text.strip())
        if words_m:
            vendor = words_m.group(1).strip()[:100]
            vendor_confidence = "low"

    # ── Invoice Number ────────────────────────
    invoice_number = None
    inv_matches = re.finditer(
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
    for m in inv_matches:
        val = m.group(2).strip()
        if val.lower() not in blacklist:
            if not val.isdigit() and len(val) < 3:
                continue
            invoice_number = val
            break

    if not invoice_number:
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
    phone_m = re.search(
        r'(?:mob(?:ile)?|tel|phone|ph)\s*[:\-]?\s*(?:\+?91[ \t]*)?([6-9]\d{9}|0\d{2,4}[\-\s]?\d{6,8})\b',
        text, re.IGNORECASE
    )
    if not phone_m:
        phone_m = re.search(r'\b([6-9]\d{9})\b', text)
    if phone_m:
        contact_number = re.sub(r'[\s\-]', '', phone_m.group(1))

    # ── Taxable Amount / GST ──────────────────
    taxable_amount = None
    gst_amount = None
    gst_percentage = None

    taxable_m = re.search(
        r'(?:sub\s*total|taxable\s*amt|taxable\s*amount|value\s*of\s*goods|basic\s*val|assessable\s*val)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
        text, re.IGNORECASE
    )
    if taxable_m:
        try:
            taxable_amount = float(taxable_m.group(1).replace(",", ""))
        except ValueError:
            pass

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
        try:
            toll_charges = float(tc_m.group(1).replace(",", ""))
        except ValueError:
            pass

    parking_charges = None
    pc_m = re.search(r'(?:parking\s*charges|parking\s*fee|parking\s*rate|parking\s*amount)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if pc_m:
        try:
            parking_charges = float(pc_m.group(1).replace(",", ""))
        except ValueError:
            pass

    other_charges = None
    oc_m = re.search(r'(?:other\s*charges|other\s*amount|misc\s*charges|misc\s*amount)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if oc_m:
        try:
            other_charges = float(oc_m.group(1).replace(",", ""))
        except ValueError:
            pass

    tds_percentage = None
    tdsp_m = re.search(r'tds\s*(?:percentage|rate|%)?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
    if tdsp_m:
        try:
            tds_percentage = float(tdsp_m.group(1))
        except ValueError:
            pass

    tds_amount = None
    tdsa_m = re.search(r'(?:tds\s*amount|tds\s*amt|tds)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)', text, re.IGNORECASE)
    if tdsa_m:
        try:
            tds_amount = float(tdsa_m.group(1).replace(",", ""))
        except ValueError:
            pass

    tax_m = re.search(
        r'(?:cgst\s*amt|sgst\s*amt|igst\s*amt|total\s*tax|tax\s*amount|gst\s*amt|vat\s*amt|vat|gst)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
        text, re.IGNORECASE
    )
    if tax_m:
        try:
            gst_amount = float(tax_m.group(1).replace(",", ""))
        except ValueError:
            pass

    pct_m = re.search(r'(?:gst|vat)\s*(?:percentage|rate|%)?\s*[:\-]?\s*([\d]+(?:\.\d+)?)\s*%', text, re.IGNORECASE)
    if pct_m:
        try:
            gst_percentage = float(pct_m.group(1))
        except ValueError:
            pass

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
        if rate_per_liter and (rate_per_liter > 250.0 or rate_per_liter <= 0.0):
            rate_per_liter = None
        if amount and liters and liters > 0.0 and not rate_per_liter:
            rate_per_liter = round(amount / liters, 2)
        elif amount and rate_per_liter and rate_per_liter > 0.0 and not liters:
            liters = round(amount / rate_per_liter, 2)
        elif liters and rate_per_liter and not amount:
            amount = round(liters * rate_per_liter, 2)
            amount_confidence = "high"

    res = {
        "category":           category,
        "expense_date":       expense_date,
        "amount":             round(amount, 2),
        "liters":             liters,
        "rate_per_liter":     rate_per_liter,
        "petrol_pump":        (petrol_pump or "")[:50] or None,
        "vendor":             (vendor or "")[:100] or None,
        "registration_no":    (registration_no or "")[:20] or None,
        "odometer":           odometer,
        "location":           (location or "")[:100] or None,
        "service_type":       (service_type or "")[:100] or None,
        "remarks":            f"[OCR] Scanned on {datetime.now().strftime('%d %b %Y %H:%M')}",
        "paid":               True,
        "invoice_number":     invoice_number,
        "taxable_amount":     taxable_amount,
        "non_taxable_amount": None,
        "gst_percentage":     gst_percentage,
        "gst_amount":         gst_amount,
        "contact_number":     contact_number,
        "raw_text":           text,
        "challan_no":         challan_no,
        "challan_type":       challan_type,
        "violation_type":     violation_type,
        "issued_by":          issued_by,
        "due_date":           due_date,
        "parking_location":   parking_location,
        "party_type":         party_type,
        "party":              party,
        "contact":            contact,
        "expense_name":       expense_name,
        "toll_charges":       toll_charges,
        "parking_charges":    parking_charges,
        "other_charges":      other_charges,
        "tds_percentage":     tds_percentage,
        "tds_amount":         tds_amount,
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
    else:  # "Other"
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
