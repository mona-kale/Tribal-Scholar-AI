GYANSETU FRONTEND + FASTAPI INTEGRATION

FILES IN THIS PACKAGE
- index.html       Updated browser frontend connected to FastAPI
- main.py          FastAPI endpoints: /, /health, /scholarships, /check-eligibility
- eligibility.py   Existing GyanSetu eligibility engine (kept compatible)
- ocr_utils.py     OCR helper used by eligibility.py and main.py

IMPORTANT
1. Keep your existing data/scholarships.json file. Do NOT overwrite it.
2. Back up your current index.html, main.py, eligibility.py and ocr_utils.py first.
3. Copy these package files into the GyanSetu project root and replace files with the same names.
4. Ensure data/scholarships.json exists and contains a non-empty "scholarships" array.
5. Tesseract OCR must be installed at:
   C:\Program Files\Tesseract-OCR\tesseract.exe

INSTALL (PowerShell)
  cd "C:\Users\MONA KALE\OneDrive\Desktop\GyanSetu"
  py -3.11 -m pip install fastapi uvicorn python-multipart pytesseract pillow

RUN BACKEND (Terminal 1)
  cd "C:\Users\MONA KALE\OneDrive\Desktop\GyanSetu"
  py -3.11 -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

RUN FRONTEND (Terminal 2)
  cd "C:\Users\MONA KALE\OneDrive\Desktop\GyanSetu"
  py -3.11 -m http.server 5500

OPEN
  http://127.0.0.1:5500/index.html

API TESTS
  http://127.0.0.1:8000/health
  http://127.0.0.1:8000/scholarships
  http://127.0.0.1:8000/docs

LIMITATIONS
- Student login and browser-side application tracking remain prototype/localStorage features.
- No production authentication, database, government portal submission, certificate authenticity check,
  or automated final approval is implemented.
- OCR output is only a reading aid. Unclear/missing income goes to manual review; officers must
  verify original documents and current official scheme notifications.
