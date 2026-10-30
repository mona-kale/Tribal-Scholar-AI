from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

import eligibility
from ocr_utils import extract_text, extract_annual_income, get_document_status

app = FastAPI(
    title="GyanSetu API",
    description="ST scholarship discovery, preliminary eligibility and OCR-assisted document review prototype.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "null",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}


def _load_schemes():
    try:
        return eligibility.load_dataset()
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Scholarship dataset load nahi hua: {exc}") from exc


def _parse_uploaded_documents(raw_value: str) -> list[str]:
    """Accept JSON array or comma-separated labels from the browser."""
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return []
    if raw_value.startswith("["):
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@app.get("/")
def home():
    return {"message": "GyanSetu API is running", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    dataset = _load_schemes()
    return {"status": "ok", "scheme_count": len(dataset.get("scholarships", []))}


@app.get("/scholarships")
def get_scholarships():
    dataset = _load_schemes()
    return {"scholarships": dataset.get("scholarships", [])}


@app.post("/check-eligibility")
async def check_eligibility_endpoint(
    scheme_id: str = Form(...),
    annual_income: str = Form(""),
    uploaded_documents: str = Form(""),
    income_certificate: Optional[UploadFile] = File(None),
):
    dataset = _load_schemes()
    scheme = eligibility.get_scheme(scheme_id, dataset)
    if scheme is None:
        raise HTTPException(status_code=404, detail=f"Scheme ID nahi mili: {scheme_id}")

    docs = _parse_uploaded_documents(uploaded_documents)
    ocr_income = None
    ocr_details = {
        "document_status": "Not Uploaded",
        "document_message": "Income certificate upload nahi kiya gaya. Original document manually verify karna hoga.",
        "possible_annual_income": None,
    }

    if income_certificate is not None and income_certificate.filename:
        content_type = (income_certificate.content_type or "").lower()
        suffix = Path(income_certificate.filename).suffix.lower()
        allowed_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
        if content_type not in ALLOWED_IMAGE_TYPES and suffix not in allowed_suffixes:
            raise HTTPException(status_code=415, detail="Income certificate ke liye JPG, PNG, WEBP, TIFF ya BMP image upload karein.")

        content = await income_certificate.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded income certificate empty hai.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image size 8 MB se kam honi chahiye.")

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".img") as temp_file:
                temp_file.write(content)
                temp_path = Path(temp_file.name)

            extracted_text = extract_text(temp_path)
            ocr_income = extract_annual_income(extracted_text)
            doc_status, doc_message = get_document_status(extracted_text, ocr_income)
            ocr_details = {
                "document_status": doc_status,
                "document_message": doc_message,
                "possible_annual_income": ocr_income,
            }

            # A selected uploaded certificate is included in the checklist only
            # after a file was actually received by the API.
            if not any("income certificate" in item.casefold() for item in docs):
                docs.append("Income certificate")

        except Exception as exc:
            # OCR failures must never be converted into a pass.
            ocr_details = {
                "document_status": "Manual Review Required",
                "document_message": f"OCR process nahi ho paya: {exc}. Original certificate manually verify karein.",
                "possible_annual_income": None,
            }
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    applicant = {
        "reported_family_income_inr": annual_income.strip() or None,
        "ocr_family_income_inr": ocr_income,
        "uploaded_documents": docs,
    }

    try:
        result = eligibility.check_eligibility(applicant, scheme)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Eligibility check fail hua: {exc}") from exc

    # Return the exact response contract expected by index.html.
    return {
        "status": "success",
        "result": result,
        "ocr_details": ocr_details,
    }
