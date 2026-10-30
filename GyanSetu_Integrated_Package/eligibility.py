import json
import math
from pathlib import Path

from ocr_utils import extract_text, extract_annual_income


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "scholarships.json"


def load_dataset():
    """Load and validate the scholarship dataset."""
    if not DATA_FILE.is_file():
        raise FileNotFoundError(f"Dataset file nahi mili: {DATA_FILE}")

    with DATA_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Dataset ka root JSON object hona chahiye.")

    scholarships = data.get("scholarships")
    if not isinstance(scholarships, list) or not scholarships:
        raise ValueError("scholarships.json mein non-empty 'scholarships' list honi chahiye.")

    seen_ids = set()
    for scheme in scholarships:
        if not isinstance(scheme, dict):
            raise ValueError("Invalid scholarship entry: har scheme object honi chahiye.")

        scheme_id = scheme.get("scheme_id")
        scheme_name = scheme.get("scheme_name")
        if not isinstance(scheme_id, str) or not scheme_id.strip():
            raise ValueError("Har scheme mein valid scheme_id honi chahiye.")
        if not isinstance(scheme_name, str) or not scheme_name.strip():
            raise ValueError(f"Scheme {scheme_id} mein valid scheme_name nahi hai.")

        normalized_id = scheme_id.strip().casefold()
        if normalized_id in seen_ids:
            raise ValueError(f"Duplicate scheme ID: {scheme_id}")
        seen_ids.add(normalized_id)

    return data


def get_scheme(scheme_id, dataset=None):
    """Find a scholarship using its scheme ID, ignoring letter case."""
    if dataset is None:
        dataset = load_dataset()

    if not isinstance(scheme_id, str):
        return None

    target_id = scheme_id.strip().casefold()
    for scheme in dataset["scholarships"]:
        if scheme.get("scheme_id", "").strip().casefold() == target_id:
            return scheme
    return None


def parse_income(value):
    """Return a finite, non-negative income amount, otherwise None."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return None

    try:
        amount = float(value)
        if math.isfinite(amount) and amount >= 0:
            return amount
    except (ValueError, TypeError, OverflowError):
        pass

    return None


def normalize_document(value):
    """Normalize common document-name variants before comparing documents."""
    if not isinstance(value, str):
        return ""

    text = " ".join(value.casefold().replace("_", " ").replace("-", " ").split())
    # Remove punctuation that commonly varies in typed document names.
    text = "".join(char for char in text if char.isalnum() or char.isspace())
    text = " ".join(text.split())

    aliases = {
        "st certificate": "tribe certificate",
        "scheduled tribe certificate": "tribe certificate",
        "tribal certificate": "tribe certificate",
        "caste certificate": "tribe certificate",
        "income proof": "income certificate",
        "family income certificate": "income certificate",
        "school enrollment proof": "school enrollment proof",
        "school enrolment proof": "school enrollment proof",
        "enrollment proof": "admission or enrollment proof",
        "enrolment proof": "admission or enrollment proof",
        "admission proof": "admission or enrollment proof",
        "admission letter": "admission or enrollment proof",
        "enrollment certificate": "admission or enrollment proof",
        "enrolment certificate": "admission or enrollment proof",
        "previous marksheet": "previous qualifying examination marksheet",
        "previous qualifying marksheet": "previous qualifying examination marksheet",
        "qualifying examination marksheet": "previous qualifying examination marksheet",
        "academic marksheets": "required academic marksheets",
        "academic marksheet": "required academic marksheets",
        "bank details": "bank account details",
        "bank passbook": "bank account details",
        "bank account proof": "bank account details",
        "aadhaar": "identity document",
        "aadhar": "identity document",
        "aadhaar card": "identity document",
        "aadhar card": "identity document",
        "identity documents": "identity document",
        "identity proof": "identity document",
        "college id": "identity document",
        "college id card": "identity document",
        "passport copy": "passport",
        "foreign university admission documents": "foreign university admission documents",
    }
    return aliases.get(text, text)


def _income_test_is_not_applicable(scheme):
    """Honor an explicit dataset note that a scheme has no income test."""
    status = str(scheme.get("income_limit_status", "")).casefold()
    return (
        scheme.get("scheme_id") == "MOTA_NFST"
        or "do not apply an income test" in status
        or "no income test" in status
    )


def check_eligibility(applicant, scheme):
    """Run preliminary configured checks; never make the final award decision."""
    if not isinstance(applicant, dict) or not isinstance(scheme, dict):
        raise TypeError("Applicant aur scheme dictionaries hone chahiye.")

    checks = []
    flags = []

    raw_income = applicant.get("reported_family_income_inr")
    income = parse_income(raw_income)
    income_limit = scheme.get("annual_family_income_limit_inr")
    income_test_not_applicable = _income_test_is_not_applicable(scheme)

    # 1. Income limit check. Some schemes explicitly do not use an income test.
    if income_test_not_applicable:
        checks.append({
            "check": "Family income limit",
            "status": "SKIPPED",
            "message": "Dataset ke mutabik is scheme ke liye income test apply nahi hota.",
        })
    else:
        if raw_income is None or (isinstance(raw_income, str) and not raw_income.strip()):
            checks.append({
                "check": "Family income",
                "status": "MISSING",
                "message": "Annual family income enter nahi ki gayi.",
            })
            flags.append("Family income missing")
        elif income is None:
            checks.append({
                "check": "Family income",
                "status": "INVALID",
                "message": "Income valid, non-negative number honi chahiye.",
            })
            flags.append("Invalid family income")

        if income_limit is None:
            checks.append({
                "check": "Configured income limit",
                "status": "MANUAL_REVIEW",
                "message": "Dataset mein income limit configured nahi hai; current official guidelines verify karein.",
            })
        else:
            limit = parse_income(income_limit)
            if limit is None:
                checks.append({
                    "check": "Configured income limit",
                    "status": "INVALID",
                    "message": "Dataset ki configured income limit invalid hai.",
                })
                flags.append("Invalid configured income limit")
            elif income is not None:
                if income <= limit:
                    checks.append({
                        "check": "Family income limit",
                        "status": "PASS",
                        "message": "Income configured limit ke andar hai; current official rule ki validity verify karein.",
                    })
                else:
                    checks.append({
                        "check": "Family income limit",
                        "status": "REVIEW",
                        "message": "Income configured limit se zyada hai.",
                    })
                    flags.append("Family income limit exceeded")
            else:
                checks.append({
                    "check": "Family income limit",
                    "status": "NOT_CHECKED",
                    "message": "Valid income ke bina limit compare nahi hui.",
                })

    # 2. Required document checklist.
    required_documents = scheme.get("documents_to_check", [])
    uploaded_documents = applicant.get("uploaded_documents", [])

    required_list_valid = (
        isinstance(required_documents, list)
        and all(isinstance(doc, str) and doc.strip() for doc in required_documents)
    )
    uploaded_list_valid = (
        isinstance(uploaded_documents, list)
        and all(isinstance(doc, str) and doc.strip() for doc in uploaded_documents)
    )

    if not required_list_valid:
        required_documents = []
        flags.append("Invalid required document configuration")
        checks.append({
            "check": "Documents",
            "status": "MANUAL_REVIEW",
            "message": "Required document checklist valid nahi hai.",
        })

    if not uploaded_list_valid:
        uploaded_documents = []
        flags.append("Invalid uploaded documents data")
        checks.append({
            "check": "Uploaded documents",
            "status": "INVALID",
            "message": "Uploaded documents ki list valid nahi hai.",
        })

    required_map = {}
    for document in required_documents:
        normalized = normalize_document(document)
        required_map.setdefault(normalized, document)

    uploaded_set = {normalize_document(document) for document in uploaded_documents}
    missing_documents = [
        original_name
        for normalized, original_name in required_map.items()
        if normalized not in uploaded_set
    ]

    if required_list_valid and uploaded_list_valid:
        if missing_documents:
            flags.append("Required documents missing")
            checks.append({
                "check": "Documents",
                "status": "MISSING",
                "message": "Kuch required documents checklist mein nahi mile.",
            })
        else:
            checks.append({
                "check": "Documents",
                "status": "MANUAL_REVIEW",
                "message": "Checklist complete hai; original documents ki authenticity verify karna baaki hai.",
            })

    # 3. Compare OCR income only where this scheme uses an income test.
    raw_ocr_income = applicant.get("ocr_family_income_inr")
    if income_test_not_applicable:
        checks.append({
            "check": "OCR income comparison",
            "status": "SKIPPED",
            "message": "Is scheme ke liye income test apply nahi hota; OCR income comparison skip ki gayi.",
        })
    elif raw_ocr_income is None or (isinstance(raw_ocr_income, str) and not raw_ocr_income.strip()):
        checks.append({
            "check": "OCR income comparison",
            "status": "MANUAL_REVIEW",
            "message": "OCR income available nahi hai. Income certificate manually verify karein.",
        })
    else:
        ocr_income = parse_income(raw_ocr_income)
        if ocr_income is None:
            flags.append("Invalid OCR income")
            checks.append({
                "check": "OCR income comparison",
                "status": "MANUAL_REVIEW",
                "message": "OCR income valid number nahi hai. Original certificate verify karein.",
            })
        elif income is None:
            checks.append({
                "check": "OCR income comparison",
                "status": "MANUAL_REVIEW",
                "message": "Form income missing ya invalid hai; comparison nahi ho sakta.",
            })
        elif abs(income - ocr_income) > 1:
            flags.append("Form income and OCR income mismatch")
            checks.append({
                "check": "OCR income comparison",
                "status": "MISMATCH",
                "message": "Form aur OCR income alag hain. Original certificate manually verify karein.",
            })
        else:
            checks.append({
                "check": "OCR income comparison",
                "status": "PASS",
                "message": "Form aur OCR income match karti hain; original certificate verify karna phir bhi zaroori hai.",
            })

    # 4. Conditions that require authorized human verification.
    checks.append({
        "check": "ST eligibility, domicile and course",
        "status": "MANUAL_REVIEW",
        "message": "ST eligibility, domicile, course aur current official scheme rules verify karein.",
    })

    if scheme.get("scheme_id") == "MOTA_TOP_CLASS_ST":
        checks.append({
            "check": "Top Class institution eligibility",
            "status": "MANUAL_REVIEW",
            "message": "Institution aur course current official scheme list mein eligible hain ya nahi, verify karein.",
        })

    workflow_status = "Needs document review" if flags else "Pending verification"
    return {
        "scheme_id": scheme.get("scheme_id"),
        "scheme_name": scheme.get("scheme_name"),
        "checks": checks,
        "verification_flags": list(dict.fromkeys(flags)),
        "missing_documents": missing_documents,
        "workflow_status": workflow_status,
        "final_decision": "Pending authorized human review",
    }


def main():
    try:
        dataset = load_dataset()
        print("\n=== GyanSetu Scholarship Eligibility ===")
        print("Available scholarship schemes:")
        for scheme in dataset["scholarships"]:
            print(f"- {scheme['scheme_id']}: {scheme['scheme_name']}")

        scheme_id = input("\nScheme ID enter karein: ").strip()
        scheme = get_scheme(scheme_id, dataset)
        if scheme is None:
            print("Scheme ID nahi mili. Dobara check karein.")
            return

        raw_income = input("Form mein annual family income (INR; agar applicable ho): ").strip()
        document_path = input("Income certificate image path (skip ke liye Enter): ").strip().strip('"').strip("'")
        ocr_income = None

        if document_path:
            try:
                extracted_text = extract_text(document_path)
                print("\n--- EXTRACTED DOCUMENT TEXT ---")
                print(extracted_text or "(Koi text nahi mila)")
                ocr_income = extract_annual_income(extracted_text)
                if ocr_income is None:
                    print("\nIncome detect nahi hui. Manual verification required.")
                else:
                    print(f"\nPossible OCR income: Rs. {ocr_income:,.2f}")
                    print("Note: OCR amount ko original certificate se verify karein.")
            except (FileNotFoundError, RuntimeError, OSError) as error:
                print(f"\nOCR ERROR: {error}")
                print("OCR income unavailable; manual review required.")

        uploaded_input = input("\nUploaded document names comma se enter karein: ").strip()
        uploaded_documents = [item.strip() for item in uploaded_input.split(",") if item.strip()]

        applicant = {
            "reported_family_income_inr": raw_income,
            "ocr_family_income_inr": ocr_income,
            "uploaded_documents": uploaded_documents,
        }
        result = check_eligibility(applicant, scheme)
        print("\n--- ELIGIBILITY RESULT ---")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"\nERROR: {error}")


if __name__ == "__main__":
    main()
