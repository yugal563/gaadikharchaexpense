import base64
import os
import httpx
import json
from fastapi import HTTPException
from io import BytesIO
from PIL import Image

def compress_image(image_bytes: bytes, max_dim: int = 1200, quality: int = 80) -> bytes:
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        width, height = img.size
        if width > max_dim or height > max_dim:
            if width > height:
                new_width = max_dim
                new_height = int(height * (max_dim / width))
            else:
                new_height = max_dim
                new_width = int(width * (max_dim / height))
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality)
        return out.getvalue()
    except Exception:
        return image_bytes

PROMPT = """
You are a receipt data extraction assistant for an Indian vehicle expense tracker.
Analyse this receipt image carefully — it may be handwritten, printed, or a mix.
The image may contain ONE or MULTIPLE separate receipts. For each distinct receipt found in the image, extract its details.

Return ONLY valid JSON (no markdown, no explanation) using the following schema:

{
    "receipts": [
        {
            "vendor":          "shop / garage / pump name",
            "expense_date":    "YYYY-MM-DD  (convert any date format found)",
            "amount":          <TOTAL / GRAND TOTAL as a plain number e.g. 3343>,
            "category":        "Fuel | Maintenance | Toll | Other",
            "location":        "city name or null",
            "registration_no": "vehicle plate number or null",
            "odometer":        <km reading as integer or null>,
            "service_type":    "Periodic Maintenance | General Service | Body Work | Car Wash | any specific service details or null, only for Maintenance receipts",
            "liters":          <fuel quantity in liters as float or null, only for Fuel receipts>,
            "rate_per_liter":  <fuel rate per liter as float or null, only for Fuel receipts>,
            "petrol_pump":     "HPCL | Indian Oil | BPCL | Shell | Nayara | Reliance | etc. or null, only for Fuel receipts",
            "is_indian_receipt": true | false
        }
    ]
}

Rules:
- amount = TOTAL / GRAND TOTAL only — never a line item
- For crossed-out numbers, use the final corrected value
- Numbers like "220-" mean 220 rupees
- Dates like D/M/YY → convert to YYYY-MM-DD (assume 20YY)
- is_indian_receipt should be true only if the receipt has Indian context (e.g., currency in ₹/Rs, Indian addresses/cities, GSTIN/GST, Indian petrol pump brands, etc.)
- Return ONLY the JSON object, nothing else
"""

async def analyze_receipt_with_azure_openai(image_bytes: bytes) -> dict:
    endpoint = os.getenv("AZURE_ENDPOINT")
    key = os.getenv("AZURE_OCR_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-nano")
    
    if not endpoint or not key:
        raise ValueError("AZURE_ENDPOINT and AZURE_OCR_KEY must be set in .env")
        
    if "/api/projects" in endpoint:
        endpoint = endpoint.split("/api/projects")[0]
    image_bytes = compress_image(image_bytes)
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"
    
    headers = {
        "api-key": key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64_image}"
                        }
                    }
                ]
            }
        ],
        "max_completion_tokens": 4096,
        "temperature": 0
    }
    
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Azure OpenAI call failed ({response.status_code}): {response.text}"
            )
        
        result = response.json()
        raw = result["choices"][0]["message"]["content"].strip()
        
        # Strip markdown code block fences if any
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            
        data = json.loads(raw)
        return data
