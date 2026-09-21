# """
# attendance_system/api/faculty/sheet_ocr.py
# OCR  : OpenRouter API — vision models (e.g. Gemini Flash, Llama Vision)
# Match: local rapidfuzz (free, no API cost)
# """

# import os
# import re
# import base64
# import logging

# from dotenv import load_dotenv
# from openai import OpenAI
# from rapidfuzz import fuzz
# from core.db import get_cursor

# load_dotenv()
# logger = logging.getLogger(__name__)

# # ─────────────────────────────────────────────
# # OpenRouter client — lazily initialised
# # ─────────────────────────────────────────────

# _client = None

# def _get_client() -> OpenAI:
#     global _client
#     if _client is None:
#         api_key = os.getenv("OPENROUTER_API_KEY")
#         if not api_key:
#             raise RuntimeError("OPENROUTER_API_KEY not set in .env")
#         _client = OpenAI(
#             base_url="https://openrouter.ai/api/v1",
#             api_key=api_key,
#         )
#     return _client


# # ─────────────────────────────────────────────
# # OCR — OpenRouter Vision
# # ─────────────────────────────────────────────

# OCR_MODEL = "openrouter/free"


# def extract_identifiers_from_image(image_path: str) -> list[str]:
#     """
#     Extract handwritten student names / USNs
#     from attendance sheet images using OpenRouter vision model.
#     """
#     from PIL import Image
#     import tempfile

#     # -----------------------------
#     # Resize large mobile images
#     # -----------------------------
#     img = Image.open(image_path)
#     img.thumbnail((2000, 2000))

#     temp_file = tempfile.NamedTemporaryFile(
#         suffix=".jpg",
#         delete=False
#     )

#     img.save(temp_file.name, format="JPEG", quality=90)

#     # -----------------------------
#     # Convert image to base64
#     # -----------------------------
#     with open(temp_file.name, "rb") as f:
#         image_b64 = base64.b64encode(f.read()).decode("utf-8")

#     # -----------------------------
#     # OCR Prompt
#     # -----------------------------
#     prompt = """
#     This image contains a handwritten college attendance sheet with student names and USNs/Roll Numbers (in 1 or 2 columns).

#     Extract ALL handwritten student names and USNs/roll numbers from the page.

#     STRICT RULES:
#     - Extract EVERY single entry (there are around 50-60 entries numbered 0) to 58)).
#     - Output ONE entry per line.
#     - DO NOT include serial numbers like "0)", "1)", "29)", "58)" in the output line — extract ONLY the student name or USN itself.
#     - Preserve student names and USNs exactly as written.
#     - Do NOT stop early or truncate output. Read both columns completely.
#     - Ignore headers, footers, page borders, and line numbers.

#     Example output:
#     1BY11CS999
#     Deepthi
#     1BY23CS001
#     Aditya Varma
#     """

#     # -----------------------------
#     # Send to OpenRouter, with fallbacks
#     # -----------------------------
#     # "openrouter/free" (random free-model router) turned out to sometimes
#     # land on a free model that returns an EMPTY response for an image
#     # input, with no error at all — the API call succeeds, but there's
#     # nothing to extract, which used to silently show as "0 students
#     # matched" with no explanation. So:
#     #   1. We pin a specific, known vision-capable free model as the FIRST
#     #      attempt (deterministic — no more roulette on every upload).
#     #   2. We retry on an EMPTY response, not just on a thrown exception.
#     #   3. We log which model actually answered and how long its reply was,
#     #      so future issues are visible in the server console immediately.
#     OCR_FALLBACK_MODELS = [
#         OCR_MODEL,
#         "openrouter/free",
#         "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
#     ]

#     raw = None
#     last_error = None
#     for attempt_model in OCR_FALLBACK_MODELS:
#         try:
#             response = _get_client().chat.completions.create(
#                 model=attempt_model,
#                 max_tokens=1500,
#                 temperature=0,
#                 messages=[
#                     {
#                         "role": "user",
#                         "content": [
#                             {
#                                 "type": "text",
#                                 "text": prompt
#                             },
#                             {
#                                 "type": "image_url",
#                                 "image_url": {
#                                     "url": f"data:image/jpeg;base64,{image_b64}"
#                                 }
#                             }
#                         ]
#                     }
#                 ]
#             )
#             content = response.choices[0].message.content
#             actual_model = getattr(response, "model", attempt_model)
#             logger.info(
#                 "OCR attempt requested_model=%s actual_model=%s reply_len=%d",
#                 attempt_model, actual_model, len(content or "")
#             )
#             if content and content.strip():
#                 raw = content.strip()
#                 break
#             logger.warning(
#                 "OCR attempt with model=%s (actual=%s) returned an EMPTY response — trying next fallback.",
#                 attempt_model, actual_model
#             )
#             last_error = RuntimeError(f"Model {actual_model} returned an empty OCR response.")
#         except Exception as e:
#             last_error = e
#             logger.warning("OCR attempt with model=%s raised an error: %s", attempt_model, e)
#             continue

#     if raw is None:
#         logger.error("All OCR model attempts failed or returned empty: %s", last_error)
#         raise RuntimeError(
#             "The OCR service couldn't read any text from this image (tried "
#             f"{len(OCR_FALLBACK_MODELS)} free models). Please retry, or try a "
#             "clearer / better-lit photo of the sheet."
#         ) from last_error

#     logger.info("OpenRouter OCR raw output:\n%s", raw)

#     print("\n========== OCR OUTPUT ==========")
#     print(raw)
#     print("================================\n")

#     # -----------------------------
#     # Clean extracted lines & strip serial numbers
#     # -----------------------------
#     lines = []

#     for line in raw.splitlines():
#         cleaned = line.strip()

#         # 1. Remove markdown bullets/dashes
#         cleaned = re.sub(r"^[\-\*\•]+", "", cleaned).strip()

#         # 2. Strip serial numbers (e.g. 0), 1), 2., 3-, 29), 58.)
#         cleaned = re.sub(r"^\s*\d+[\)\.\:\-\/\]\}\s]+", "", cleaned).strip()
#         cleaned = re.sub(r"^\s*\d+\s+", "", cleaned).strip()

#         # 3. Remove unwanted non-alphanumeric symbols except spaces and dots
#         cleaned = re.sub(r"[^A-Za-z0-9 .]", "", cleaned).strip()

#         # 4. Normalize multiple spaces
#         cleaned = re.sub(r"\s+", " ", cleaned)

#         # Ignore empty/small noise
#         if len(cleaned) < 2:
#             continue

#         # Ignore non-name header words
#         lower = cleaned.lower()
#         skip_words = [
#             "attendance", "subject", "date", "signature",
#             "faculty", "present", "absent", "semester", "section"
#         ]

#         if any(word in lower for word in skip_words):
#             continue

#         lines.append(cleaned)

#     # -----------------------------
#     # Remove duplicates
#     # -----------------------------
#     unique_lines = []
#     seen = set()

#     for item in lines:
#         key = item.upper()
#         if key not in seen:
#             seen.add(key)
#             unique_lines.append(item)

#     logger.info("Final extracted identifiers (%d): %s", len(unique_lines), unique_lines)
#     return unique_lines


# # ─────────────────────────────────────────────
# # USN HELPERS
# # ─────────────────────────────────────────────

# def looks_like_usn(text: str) -> bool:
#     """
#     True if text matches USN / Roll number format.
#     """
#     cleaned = text.strip().upper()
#     return bool(
#         re.match(r"^[1-9][A-Z0-9]{2}\d{2}[A-Z]{2,3}\d{3}$", cleaned) or
#         re.match(r"^[A-Z]\d{3,4}$", cleaned) or
#         re.match(r"^[0-9A-Z]{5,12}$", cleaned)
#     )


# def _fuzzy_usn_match(ocr_usn: str, usn_map: dict):
#     """
#     Handle common OCR character confusions for USNs.
#     e.g. O↔0, I↔1, S↔5, B↔8, Z↔2
#     """
#     confusion = {
#         "O": "0", "0": "O",
#         "I": "1", "1": "I",
#         "S": "5", "5": "S",
#         "B": "8", "8": "B",
#         "Z": "2",
#     }
#     for i, ch in enumerate(ocr_usn.upper()):
#         if ch in confusion:
#             candidate = ocr_usn[:i] + confusion[ch] + ocr_usn[i + 1:]
#             if candidate.upper() in usn_map:
#                 logger.info("Fuzzy USN: %s → %s", ocr_usn, candidate)
#                 return usn_map[candidate.upper()]
#     return None


# # ─────────────────────────────────────────────
# # STUDENT MATCHING — fully local, no API cost
# # ─────────────────────────────────────────────

# def match_students(identifiers: list[str], section_id: int) -> dict:
#     """
#     Match OCR'd identifiers against students enrolled in the section.
#     """
#     cursor = get_cursor()
#     cursor.execute(
#         """
#         SELECT st.id AS student_id, st.usn, u.full_name
#         FROM students st
#         JOIN users u ON u.id = st.user_id
#         WHERE st.section_id = %s
#         """,
#         (section_id,),
#     )
#     all_students = cursor.fetchall()

#     usn_map  = {s["usn"].strip().upper(): s for s in all_students}
#     name_map = {s["full_name"].strip().upper(): s for s in all_students}

#     matched, unmatched = [], []

#     for raw in identifiers:
#         # Strip any residual leading serial numbers if present (e.g. "29) Aditya Varma" -> "Aditya Varma")
#         cleaned_raw = re.sub(r"^\s*\d+[\)\.\:\-\/\]\}\s]*", "", raw).strip()
#         key = cleaned_raw.upper()
#         if not key:
#             continue

#         # 1. Exact USN
#         if key in usn_map:
#             matched.append(usn_map[key])
#             continue

#         # 2. Exact full name
#         if key in name_map:
#             matched.append(name_map[key])
#             continue

#         # 3. Fuzzy USN (character confusion)
#         if looks_like_usn(key):
#             best = _fuzzy_usn_match(key, usn_map)
#             if best:
#                 matched.append(best)
#                 continue

#         # 4. Substring name (e.g. OCR read "Rahul", DB has "Rahul Kumar")
#         found = next(
#             (s for s in all_students if key in s["full_name"].upper() or s["full_name"].upper() in key),
#             None
#         )
#         if found:
#             matched.append(found)
#             continue

#         # 5. Fuzzy token name
#         best_match, best_score = None, 0
#         for s in all_students:
#             score = fuzz.token_sort_ratio(key, s["full_name"].upper())
#             if score > best_score:
#                 best_score = score
#                 best_match = s

#         if best_score >= 68:
#             logger.info(
#                 "Fuzzy name: '%s' → '%s' (score %d)",
#                 key, best_match["full_name"], best_score
#             )
#             matched.append(best_match)
#             continue

#         unmatched.append(raw)

#     # Deduplicate — same student matched by both name and USN on sheet
#     seen, deduped = set(), []
#     for s in matched:
#         if s["student_id"] not in seen:
#             seen.add(s["student_id"])
#             deduped.append(s)

#     return {"matched": deduped, "unmatched": unmatched}



"""
attendance_system/api/faculty/sheet_ocr.py
OCR  : OpenRouter API — vision models (e.g. Gemini Flash, Llama Vision)
Match: local rapidfuzz (free, no API cost)
"""

import os
import re
import base64
import logging

from dotenv import load_dotenv
from openai import OpenAI
from rapidfuzz import fuzz
from core.db import get_cursor

load_dotenv()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# OpenRouter client — lazily initialised
# ─────────────────────────────────────────────

_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set in .env")
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            # Without an explicit timeout, a provider that never responds
            # (which does happen with some free-tier models) hangs the
            # whole Flask request indefinitely instead of failing fast and
            # letting the fallback loop move on to the next model.
            timeout=35.0,
            # IMPORTANT: disable openai's built-in auto-retry.
            # By default it retries 2× on 429 errors, adding ~60 s of
            # dead wait before we even reach our own fallback list.
            # We handle retries ourselves via OCR_FALLBACK_MODELS below.
            max_retries=0,
        )
    return _client


# ─────────────────────────────────────────────
# OCR — OpenRouter Vision
# ─────────────────────────────────────────────
#
# Model history (updated 2026-09-09):
#   • google/gemma-4-31b-it:free       — rate-limited 429 (Google AI Studio shared pool)
#   • google/gemma-4-26b-a4b-it:free   — rate-limited 429 (same shared pool)
#   • nvidia/nemotron-3-…:free         — works but very slow, not a dedicated vision model
#
# Current strategy: use Llama-4 Scout (Meta's dedicated vision model, free
# on OpenRouter) as primary, with Qwen2.5-VL as first fallback (strong OCR
# on handwritten text), then nvidia nemotron as last resort.
OCR_MODEL = "meta-llama/llama-4-scout:free"


def extract_identifiers_from_image(image_path: str) -> list[str]:
    """
    Extract handwritten student names / USNs
    from attendance sheet images using OpenRouter vision model.
    """
    from PIL import Image
    import tempfile

    # -----------------------------
    # Resize large mobile images
    # -----------------------------
    img = Image.open(image_path)
    img.thumbnail((2000, 2000))

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".jpg",
        delete=False
    )

    img.save(temp_file.name, format="JPEG", quality=90)

    # -----------------------------
    # Convert image to base64
    # -----------------------------
    with open(temp_file.name, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    # -----------------------------
    # OCR Prompt
    # -----------------------------
    prompt = """
    This image contains a handwritten college attendance sheet with student names and USNs/Roll Numbers (in 1 or 2 columns).

    Extract ALL handwritten student names and USNs/roll numbers from the page.

    STRICT RULES:
    - Extract EVERY single entry (there are around 50-60 entries numbered 0) to 58)).
    - Output ONE entry per line.
    - DO NOT include serial numbers like "0)", "1)", "29)", "58)" in the output line — extract ONLY the student name or USN itself.
    - Preserve student names and USNs exactly as written.
    - Do NOT stop early or truncate output. Read both columns completely.
    - Ignore headers, footers, page borders, and line numbers.

    Example output:
    1BY11CS999
    Deepthi
    1BY23CS001
    Aditya Varma
    """

    # -----------------------------
    # Send to OpenRouter, with fallbacks + per-model retries
    # -----------------------------
    # Strategy:
    #   • Each model is tried up to MAX_RETRIES_PER_MODEL times.
    #   • On a transient connection error, wait RETRY_SLEEP seconds and retry
    #     the SAME model before moving on (connection blips are common on free tier).
    #   • On a hard error (404, 400, 429) skip to next model immediately.
    #   • On an empty content response, skip to next model immediately.
    #   • openai client has max_retries=0 so errors surface instantly.
    import time

    OCR_FALLBACK_MODELS = [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",   # CONFIRMED WORKING ✓ (returns 842 chars)
        # All other free models tested and found invalid on this account:
        # meta/llama-3.2-11b-vision-instruct:free → 400 invalid model ID
        # google/gemini-2.0-flash-exp:free         → 404 no endpoints
        # google/gemma-4-31b-it:free               → 429 rate-limited
        # google/gemma-4-26b-a4b-it:free           → 429 rate-limited
        # meta-llama/llama-4-scout:free            → 404 paid only
        # qwen/qwen2.5-vl-7b-instruct:free         → 400 invalid
        # moondream/moondream2:free                → 400 invalid
    ]
    MAX_RETRIES_PER_MODEL = 4    # retry nvidia up to 4x on transient connection errors
    RETRY_SLEEP = 5              # seconds to wait between retries

    raw = None
    last_error = None

    for attempt_model in OCR_FALLBACK_MODELS:
        for attempt_num in range(1, MAX_RETRIES_PER_MODEL + 1):
            try:
                logger.info("OCR trying model=%s attempt=%d/%d", attempt_model, attempt_num, MAX_RETRIES_PER_MODEL)
                response = _get_client().chat.completions.create(
                    model=attempt_model,
                    max_tokens=1500,
                    temperature=0,
                    timeout=40.0,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}"
                                    }
                                }
                            ]
                        }
                    ]
                )
                choice = response.choices[0]
                # Reasoning models (e.g. nvidia nemotron) may put answer in
                # reasoning_content instead of content — check both.
                content = choice.message.content
                if not content:
                    content = getattr(choice.message, "reasoning_content", None)
                actual_model = getattr(response, "model", attempt_model)
                logger.info(
                    "OCR attempt requested_model=%s actual_model=%s attempt=%d reply_len=%d",
                    attempt_model, actual_model, attempt_num, len(content or "")
                )
                if content and content.strip():
                    raw = content.strip()
                    break  # success — exit retry loop
                # Empty response → skip to next model (no point retrying)
                logger.warning(
                    "OCR model=%s attempt=%d returned EMPTY — moving to next model.",
                    attempt_model, attempt_num
                )
                last_error = RuntimeError(f"Model {actual_model} returned an empty OCR response.")
                break  # break retry loop, move to next model

            except Exception as e:
                error_str = str(e)
                last_error = e
                # Hard errors (404 invalid model, 400 bad request, 402 credit):
                # no point retrying the same model.
                if any(code in error_str for code in ["404", "400", "402"]):
                    logger.warning("OCR model=%s hard error (skip model): %s", attempt_model, e)
                    break  # break retry loop, move to next model
                # Transient errors (connection error, 429 rate limit, 500 server):
                # retry after a short sleep.
                logger.warning(
                    "OCR model=%s attempt=%d/%d transient error: %s — %s",
                    attempt_model, attempt_num, MAX_RETRIES_PER_MODEL, e,
                    f"retrying in {RETRY_SLEEP}s" if attempt_num < MAX_RETRIES_PER_MODEL else "giving up on this model"
                )
                if attempt_num < MAX_RETRIES_PER_MODEL:
                    time.sleep(RETRY_SLEEP)
                # else: loop ends naturally, moves to next model

        if raw is not None:
            break  # found a good response — exit model loop

    if raw is None:
        logger.error("All OCR model attempts failed or returned empty: %s", last_error)
        raise RuntimeError(
            "The OCR service couldn't read any text from this image (tried "
            f"{len(OCR_FALLBACK_MODELS)} free models). Please retry, or try a "
            "clearer / better-lit photo of the sheet."
        ) from last_error

    logger.info("OpenRouter OCR raw output:\n%s", raw)

    print("\n========== OCR OUTPUT ==========")
    print(raw)
    print("================================\n")

    # -----------------------------
    # Clean extracted lines & strip serial numbers
    # -----------------------------
    lines = []

    for line in raw.splitlines():
        cleaned = line.strip()

        # 1. Remove markdown bullets/dashes
        cleaned = re.sub(r"^[\-\*\•]+", "", cleaned).strip()

        # 2a. Strip LEADING serial numbers (e.g. 0), 1), 2., 3-, 29), 58.)
        cleaned = re.sub(r"^\s*\d+[\)\.\:\-\/\]\}\s]+", "", cleaned).strip()
        cleaned = re.sub(r"^\s*\d+\s+", "", cleaned).strip()

        # 2b. Strip TRAILING serial numbers — nvidia appends them as "Name - N"
        #     e.g. "Deepthi - 1" → "Deepthi", "Soma - 4" → "Soma"
        cleaned = re.sub(r"\s*[-–]\s*\d+\s*$", "", cleaned).strip()
        # Also strip plain trailing number "Name 12" → "Name"
        cleaned = re.sub(r"\s+\d+\s*$", "", cleaned).strip()

        # 3. Remove unwanted non-alphanumeric symbols except spaces and dots
        cleaned = re.sub(r"[^A-Za-z0-9 .]", "", cleaned).strip()

        # 4. Normalize multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned)

        # Ignore empty/small noise
        if len(cleaned) < 2:
            continue

        # Ignore non-name header words
        lower = cleaned.lower()
        skip_words = [
            "attendance", "subject", "date", "signature",
            "faculty", "present", "absent", "semester", "section"
        ]

        if any(word in lower for word in skip_words):
            continue

        lines.append(cleaned)

    # -----------------------------
    # Remove duplicates
    # -----------------------------
    unique_lines = []
    seen = set()

    for item in lines:
        key = item.upper()
        if key not in seen:
            seen.add(key)
            unique_lines.append(item)

    logger.info("Final extracted identifiers (%d): %s", len(unique_lines), unique_lines)
    return unique_lines


# ─────────────────────────────────────────────
# USN HELPERS
# ─────────────────────────────────────────────

def looks_like_usn(text: str) -> bool:
    """
    True if text matches USN / Roll number format.
    """
    cleaned = text.strip().upper()
    return bool(
        re.match(r"^[1-9][A-Z0-9]{2}\d{2}[A-Z]{2,3}\d{3}$", cleaned) or
        re.match(r"^[A-Z]\d{3,4}$", cleaned) or
        re.match(r"^[0-9A-Z]{5,12}$", cleaned)
    )


def _fuzzy_usn_match(ocr_usn: str, usn_map: dict):
    """
    Handle common OCR character confusions for USNs.
    e.g. O↔0, I↔1, S↔5, B↔8, Z↔2
    """
    confusion = {
        "O": "0", "0": "O",
        "I": "1", "1": "I",
        "S": "5", "5": "S",
        "B": "8", "8": "B",
        "Z": "2",
    }
    for i, ch in enumerate(ocr_usn.upper()):
        if ch in confusion:
            candidate = ocr_usn[:i] + confusion[ch] + ocr_usn[i + 1:]
            if candidate.upper() in usn_map:
                logger.info("Fuzzy USN: %s → %s", ocr_usn, candidate)
                return usn_map[candidate.upper()]
    return None


# ─────────────────────────────────────────────
# STUDENT MATCHING — fully local, no API cost
# ─────────────────────────────────────────────

def match_students(identifiers: list[str], section_id: int) -> dict:
    """
    Match OCR'd identifiers against students enrolled in the section.
    """
    cursor = get_cursor()
    cursor.execute(
        """
        SELECT st.id AS student_id, st.usn, u.full_name
        FROM students st
        JOIN users u ON u.id = st.user_id
        WHERE st.section_id = %s
        """,
        (section_id,),
    )
    all_students = cursor.fetchall()

    usn_map  = {s["usn"].strip().upper(): s for s in all_students}
    name_map = {s["full_name"].strip().upper(): s for s in all_students}

    matched, unmatched = [], []

    for raw in identifiers:
        # Strip any residual leading serial numbers if present (e.g. "29) Aditya Varma" -> "Aditya Varma")
        cleaned_raw = re.sub(r"^\s*\d+[\)\.\:\-\/\]\}\s]*", "", raw).strip()
        key = cleaned_raw.upper()
        if not key:
            continue

        # 1. Exact USN
        if key in usn_map:
            matched.append(usn_map[key])
            continue

        # 2. Exact full name
        if key in name_map:
            matched.append(name_map[key])
            continue

        # 3. Fuzzy USN (character confusion)
        if looks_like_usn(key):
            best = _fuzzy_usn_match(key, usn_map)
            if best:
                matched.append(best)
                continue

        # 4. Substring name (e.g. OCR read "Rahul", DB has "Rahul Kumar")
        found = next(
            (s for s in all_students if key in s["full_name"].upper() or s["full_name"].upper() in key),
            None
        )
        if found:
            matched.append(found)
            continue

        # 5. Fuzzy token name
        best_match, best_score = None, 0
        for s in all_students:
            score = fuzz.token_sort_ratio(key, s["full_name"].upper())
            if score > best_score:
                best_score = score
                best_match = s

        if best_score >= 68:
            logger.info(
                "Fuzzy name: '%s' → '%s' (score %d)",
                key, best_match["full_name"], best_score
            )
            matched.append(best_match)
            continue

        unmatched.append(raw)

    # Deduplicate — same student matched by both name and USN on sheet
    seen, deduped = set(), []
    for s in matched:
        if s["student_id"] not in seen:
            seen.add(s["student_id"])
            deduped.append(s)

    return {"matched": deduped, "unmatched": unmatched}