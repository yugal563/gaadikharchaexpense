import os
import base64
import asyncio
import httpx
from fastapi import HTTPException

AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_OCR_KEY = os.getenv("AZURE_OCR_KEY")
MODEL_ID = os.getenv("MODEL_ID", "prebuilt-receipt")

async def submit_prebuilt_receipt(image_bytes: bytes) -> dict:
    """Submit image to Azure Document Intelligence model and return parsed receipt.
    Returns a dict with keys like 'MerchantName', 'TransactionDate', 'Total', 'Items'.
    """
    analyze_url = (
        f"{AZURE_ENDPOINT.rstrip('/')}/documentintelligence/documentModels/{MODEL_ID}:analyze?api-version=2024-11-30"
    )
    submit_headers = {
        "Ocp-Apim-Subscription-Key": AZURE_OCR_KEY,
        "Content-Type": "application/json",
    }
    poll_headers = {"Ocp-Apim-Subscription-Key": AZURE_OCR_KEY}
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {"base64Source": b64_image}

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(analyze_url, headers=submit_headers, json=payload)
        if response.status_code != 202:
            raise HTTPException(
                status_code=502,
                detail=f"Azure receipt model submission failed ({response.status_code}): {response.text}",
            )
        operation_url = response.headers.get("Operation-Location")
        if not operation_url:
            raise HTTPException(status_code=502, detail="Azure did not return an Operation-Location header.")
        for _ in range(40):
            await asyncio.sleep(0.5)
            poll = await client.get(operation_url, headers=poll_headers)
            result = poll.json()
            status = result.get("status", "")
            if status == "succeeded":
                analyze_result = result.get("analyzeResult", {})
                documents = analyze_result.get("documents", [])
                if documents:
                    doc = documents[0]
                    fields = doc.get("fields", {})
                    return {
                        "MerchantName": fields.get("MerchantName", {}).get("valueString", ""),
                        "TransactionDate": fields.get("TransactionDate", {}).get("valueDate", ""),
                        "Total": fields.get("Total", {}).get("valueNumber", 0),
                        "Items": fields.get("Items", {}).get("valueArray", []),
                    }
                return {}
            if status == "failed":
                raise HTTPException(status_code=502, detail="Azure receipt model processing failed.")
        raise HTTPException(status_code=504, detail="Azure receipt model timed out after 20 seconds.")
