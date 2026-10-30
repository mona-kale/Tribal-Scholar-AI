import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


# Project-relative paths work without hard-coding the project folder.
BASE_DIR = Path(__file__).resolve().parent

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


def resolve_path(document_path):
    """Resolve an absolute or project-relative image path."""
    path = Path(document_path).expanduser()

    if not path.is_absolute():
        path = BASE_DIR / path

    path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Document image nahi mili: {path}")

    return path


def _ocr_text_score(text):
    """Prefer OCR output containing more readable words, not just more characters."""
    words = re.findall(r"[A-Za-z]{2,}", text or "")
    return (len(words), len(text or ""))


def extract_text(document_path):
    """
    Extract text using a few OCR preprocessing/layout options.
    This may improve readability, but cannot recover text that is not visible.
    """
    path = resolve_path(document_path)

    try:
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")

            # Enlarge small scans, while avoiding excessive image dimensions.
            smallest_side = min(image.size)
            if smallest_side < 1400:
                scale = min(2.0, 1400 / smallest_side)
                image = image.resize(
                    (int(image.width * scale), int(image.height * scale)),
                    Image.Resampling.LANCZOS,
                )

            gray = ImageOps.autocontrast(ImageOps.grayscale(image))
            enhanced = ImageEnhance.Contrast(gray).enhance(1.7)
            sharpened = enhanced.filter(ImageFilter.SHARPEN)
            thresholded = sharpened.point(
                lambda pixel: 255 if pixel > 165 else 0
            )

            candidates = []
            # Different page segmentation modes can work better for certificates.
            for processed_image in (gray, sharpened, thresholded):
                for psm in (6, 11, 4):
                    text = pytesseract.image_to_string(
                        processed_image,
                        lang="eng",
                        config=f"--oem 3 --psm {psm}",
                    ).strip()
                    if text:
                        candidates.append(text)

            if not candidates:
                return ""

            # Select the output with the most readable words.
            return max(candidates, key=_ocr_text_score)

    except pytesseract.TesseractNotFoundError as error:
        raise RuntimeError(
            "Tesseract OCR nahi mila. TESSERACT_PATH check karo."
        ) from error
    except Exception as error:
        raise RuntimeError(
            f"Image process nahi ho payi: {error}"
        ) from error


def check_document_quality(text):
    """
    Estimate whether OCR returned enough readable text.
    Readability does not prove certificate authenticity.
    """
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    words = re.findall(r"[A-Za-z]{2,}", cleaned)

    if len(cleaned) < 40 or len(words) < 6:
        return (
            "Re-upload Required",
            "Document se readable text nahi mila. Clear image dobara upload karein.",
        )

    return (
        "Under Verification",
        "Text extract hua hai. Required details aur certificate verify karna baaki hai.",
    )


def extract_annual_income(text):
    """
    Return a possible annual income only when a clear numeric amount with
    an explicit currency marker appears near an annual-income label.

    Does not infer annual income from monthly income or guess OCR characters.
    The result must be checked against the original certificate.
    """
    if not text:
        return None

    normalized = text.replace("₹", " Rs ")
    normalized = re.sub(r"[ \t]+", " ", normalized)

    income_label = (
        r"(?:annual\s+(?:family\s+)?income"
        r"|yearly\s+(?:family\s+)?income"
        r"|income\s+from\s+all\s+sources)"
    )

    # Examples accepted: Rs. 2,40,000 / INR 240000 / Rs 240000.00
    amount = (
        r"(?P<amount>"
        r"(?:\d{1,3}(?:,\d{2,3})+|\d+)"
        r"(?:\.\d{1,2})?"
        r")"
    )
    currency = r"(?:rs\.?|inr)\s*[:.\-]*\s*"

    patterns = [
        # Annual-income label followed by currency and amount.
        income_label + r"[\s\S]{0,220}?" + currency + amount
        + r"(?![A-Za-z0-9])",

        # Currency and amount followed shortly by an annual-income label.
        currency + amount + r"[\s\S]{0,100}?" + income_label,
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue

        raw_amount = match.group("amount").replace(",", "")
        try:
            value = float(raw_amount)
        except (ValueError, OverflowError):
            continue

        if value > 0:
            return value

    return None


def get_document_status(text, annual_income):
    """Evaluate readability and income extraction separately."""
    quality_status, quality_message = check_document_quality(text)

    if quality_status == "Re-upload Required":
        return quality_status, quality_message

    if annual_income is None:
        return (
            "Manual Review Required",
            "Annual income confidently detect nahi hui. Certificate manually check karein.",
        )

    return (
        "Under Verification",
        "Possible annual income detect hui hai. Amount aur certificate officer verify karega.",
    )


def main():
    print("\n=== GyanSetu Income Certificate OCR ===")
    print("Image ka path enter karo, ya exit ke liye q likho.")

    while True:
        document_path = input("\nDocument image path: ").strip()

        if document_path.lower() == "q":
            print("Program band ho gaya.")
            break

        document_path = document_path.strip('"').strip("'")

        try:
            text = extract_text(document_path)

            print("\n--- EXTRACTED TEXT ---")
            print(text if text else "(Koi text nahi mila)")

            annual_income = extract_annual_income(text)
            status, message = get_document_status(text, annual_income)

            print("\n--- DOCUMENT RESULT ---")
            print("STATUS:", status)
            print("MESSAGE:", message)

            if annual_income is not None:
                print(f"POSSIBLE ANNUAL INCOME: Rs. {annual_income:,.2f}")
                print(
                    "NOTE: Amount OCR result hai; original certificate se verify karein."
                )
            else:
                print("POSSIBLE ANNUAL INCOME: Detect nahi hui")

        except (FileNotFoundError, RuntimeError) as error:
            print("\nERROR:", error)
        except Exception as error:
            print("\nUnexpected error:", error)


if __name__ == "__main__":
    main()
