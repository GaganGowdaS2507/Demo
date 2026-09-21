"""
attendance_system/api/mobile/voice_search.py

Pure-Python helper: parse a raw speech-to-text transcript and match it
against a session roster dict list (each item must have at least
``student_id``, ``usn``, and ``name`` keys).

No fuzzy matching is used — only exact / token-based matching so that an
acoustic error can never silently mark the wrong student.

Returns a dict with keys:
  status : "exact" | "multiple" | "not_found"
  matches: list of matching roster dicts (up to all roster students)
  parsed : dict describing what identifier was extracted from the transcript
           { "type": "usn"|"roll"|"name", "value": str }
"""

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# STT normalisation helpers
# ---------------------------------------------------------------------------

_WORD_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20",
    "twenty one": "21", "twenty two": "22", "twenty three": "23",
    "twenty four": "24", "twenty five": "25", "twenty six": "26",
    "twenty seven": "27", "twenty eight": "28", "twenty nine": "29",
    "thirty": "30",
}

# Spoken-letter confusions common in USN speech recognition (e.g. "one bm" -> "1BM")
_LETTER_SPOKEN = {
    "ay": "a", "bee": "b", "cee": "c", "dee": "d", "ee": "e",
    "ef": "f", "gee": "g", "aitch": "h", "eye": "i", "jay": "j",
    "kay": "k", "el": "l", "em": "m", "en": "n", "oh": "o",
    "pee": "p", "cue": "q", "arr": "r", "ess": "s", "tee": "t",
    "you": "u", "vee": "v", "double you": "w", "ex": "x",
    "why": "y", "zee": "z", "zed": "z",
}


def _normalize_text(text: str) -> str:
    """Lowercase, strip diacritics, collapse extra whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.strip().lower())


def _words_to_digits(text: str) -> str:
    """Replace spoken number words with digits (longest match first)."""
    for phrase, digit in sorted(_WORD_DIGITS.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"\b" + re.escape(phrase) + r"\b", digit, text)
    return text


def _spoken_letters_to_alpha(text: str) -> str:
    """Replace spoken letter names with the actual letter."""
    for phrase, letter in sorted(_LETTER_SPOKEN.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"\b" + re.escape(phrase) + r"\b", letter, text)
    return text


def _normalize_usn_candidate(raw: str) -> str:
    """
    Produce a cleaned-up USN candidate from a raw STT string.
    Strips spaces, uppercases, replaces spoken words where safe.
    """
    t = _normalize_text(raw)
    t = _words_to_digits(t)
    t = _spoken_letters_to_alpha(t)
    # Remove all spaces — USNs are compact like 1BM22CS001
    t = re.sub(r"\s+", "", t).upper()
    return t


# Patterns tried in priority order
_USN_PATTERN = re.compile(
    r"(?:usn|u\.?s\.?n\.?|student\s+id|id)\s+([a-z0-9 ]+?)(?:\s+(?:present|absent|here|attended|not\s+present|not\s+here)|\s*$)",
    re.IGNORECASE,
)
_ROLL_PATTERN = re.compile(
    r"(?:roll(?:\s+number)?|roll\s*no\.?|number)\s+(\w+)(?:\s+(?:present|absent|here|attended|not\s+present|not\s+here)|\s*$)",
    re.IGNORECASE,
)
_NAME_PATTERN = re.compile(
    r"(?:mark|add|set|put)?\s*([a-z][a-z '.,-]+?)\s+(?:present|absent|here|attended|not\s+present|not\s+here)",
    re.IGNORECASE,
)

# Words/phrases that indicate the *status* the faculty spoke, independent of
# which identifier pattern (usn / roll / name) matched. Checked separately
# from the identifier so that e.g. "Mark Gagan Gowda absent" is never
# silently treated as "present" just because the identifier regex matched.
_ABSENT_PHRASES = ("not present", "not here", "absent", "missing")
_PRESENT_PHRASES = ("present", "here", "attended")


def _extract_status(normalized_text: str) -> str | None:
    """
    Look for an explicit present/absent word anywhere in the (already
    lower-cased) transcript. Absent-style phrases are checked first so that
    negated forms like "not present" are never mis-read as present.
    Returns "present", "absent", or None if no status word was spoken.
    """
    for phrase in _ABSENT_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", normalized_text):
            return "absent"
    for phrase in _PRESENT_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", normalized_text):
            return "present"
    return None


def parse_transcript(transcript: str) -> dict:
    """
    Parse a raw STT transcript and return:
      {
        "type": "usn"|"roll"|"name"|"unknown",
        "value": <normalised string>,
        "status": "present"|"absent"|None   # explicit status word, if any
      }
    The "status" key is what the "name + status" voice-attendance mode uses
    to decide whether to mark present or absent — it must never be assumed.
    """
    t = _normalize_text(transcript)
    status = _extract_status(t)

    # 1. Try USN extraction
    m = _USN_PATTERN.search(t)
    if m:
        raw_usn = m.group(1).strip()
        norm_usn = _normalize_usn_candidate(raw_usn)
        if norm_usn:
            return {"type": "usn", "value": norm_usn, "status": status}

    # 2. Try roll-number extraction
    m = _ROLL_PATTERN.search(t)
    if m:
        raw_roll = m.group(1).strip()
        norm_roll = _words_to_digits(_normalize_text(raw_roll))
        norm_roll = re.sub(r"\s+", "", norm_roll)
        if norm_roll.isdigit():
            return {"type": "roll", "value": norm_roll, "status": status}

    # 3. Try name extraction
    m = _NAME_PATTERN.search(t)
    if m:
        name_candidate = re.sub(r"\s+", " ", m.group(1).strip())
        # Discard trivial single-char matches or stop-word captures
        if len(name_candidate) >= 3:
            return {"type": "name", "value": name_candidate.title(), "status": status}

    return {"type": "unknown", "value": t, "status": status}


# ---------------------------------------------------------------------------
# Lenient "bare identifier" parser — used by the bulk default-then-exceptions
# voice modes, where the faculty just reads a name / USN / roll number with
# no "mark ... present/absent" phrasing at all (the status is implied by
# which bulk mode is active, not spoken).
# ---------------------------------------------------------------------------

_STATUS_WORDS = {"present", "absent", "here", "attended"}


def _strip_trailing_status_word(t: str) -> str:
    """Drop a trailing present/absent/here/attended word if the faculty said
    one anyway while in a bulk mode — it's harmless, just ignored."""
    tokens = t.split()
    while tokens and tokens[-1] in _STATUS_WORDS:
        tokens.pop()
    return " ".join(tokens)


def parse_bare_identifier(transcript: str) -> dict:
    """
    Parse a bare roster identifier (no status keyword expected) spoken while
    a bulk "default present/absent, then read exceptions" voice mode is
    active. Tries USN shape, then a pure roll number, then falls back to a
    spoken name. Returns the same shape as parse_transcript() but "status"
    is always None (the caller — the active bulk mode — decides the status).
    """
    t = _normalize_text(transcript)
    t = _strip_trailing_status_word(t)
    if not t:
        return {"type": "unknown", "value": t, "status": None}

    # USN-shaped: normalise like a USN and check it has both letters and
    # digits and is reasonably long (real USNs are ~10 chars, e.g. 1BM22CS001)
    usn_candidate = _normalize_usn_candidate(t)
    if (
        len(usn_candidate) >= 6
        and re.search(r"[0-9]", usn_candidate)
        and re.search(r"[A-Z]", usn_candidate)
    ):
        return {"type": "usn", "value": usn_candidate, "status": None}

    # Pure digits -> roll number (position in the alphabetically sorted roster)
    digits_only = re.sub(r"\s+", "", _words_to_digits(t))
    if digits_only.isdigit():
        return {"type": "roll", "value": digits_only, "status": None}

    # Otherwise treat the whole (cleaned) phrase as a spoken name
    name_candidate = re.sub(r"\s+", " ", t).strip()
    if len(name_candidate) >= 2:
        return {"type": "name", "value": name_candidate.title(), "status": None}

    return {"type": "unknown", "value": t, "status": None}

# ---------------------------------------------------------------------------
# Enhanced Roster Matcher (Exact, Compact, Token Subset, & Fuzzy Matching)
# ---------------------------------------------------------------------------

import difflib

def search_roster(
    parsed: dict,
    roster: list[dict[str, Any]],
) -> dict:
    """
    Match a parsed identifier against a roster.
    Supports exact, compact (space-free), token subset, and fuzzy string matching.
    """
    id_type = parsed["type"]
    value = parsed["value"]
    raw_query = _normalize_text(value)
    q_with_digits = _words_to_digits(raw_query)
    q_compact = re.sub(r"\s+", "", raw_query)
    q_compact_digits = re.sub(r"\s+", "", q_with_digits)

    matches: list[dict] = []

    # ------------------------------------------------------------------ USN / Compact Match
    if id_type == "usn":
        norm_value = _normalize_usn_candidate(value)
        for student in roster:
            student_usn = re.sub(r"\s+", "", (student.get("usn") or "")).upper()
            if student_usn == norm_value:
                matches = [student]
                break

        if not matches:
            suffix = norm_value[-6:] if len(norm_value) >= 6 else norm_value
            candidates = [
                s for s in roster
                if re.sub(r"\s+", "", (s.get("usn") or "")).upper().endswith(suffix)
            ]
            if candidates:
                matches = candidates

    # ------------------------------------------------------------ Roll number
    elif id_type == "roll":
        try:
            idx = int(value) - 1
            if 0 <= idx < len(roster):
                matches = [roster[idx]]
        except (ValueError, TypeError):
            pass

    # ------------------------------------------------------------------ Name / Fallback
    if not matches:
        exact_name: list[dict] = []
        compact_matches: list[dict] = []
        token_matches: list[dict] = []

        q_clean = re.sub(r"\b(mark|add|set|put|present|absent|here|attended|usn|roll|number)\b", "", raw_query, flags=re.IGNORECASE).strip()
        q_tokens = [w for w in q_clean.split() if w]
        if not q_tokens:
            q_tokens = raw_query.split()

        for student in roster:
            student_name_norm = _normalize_text(student.get("name") or "")
            student_usn_norm = _normalize_text(student.get("usn") or "")
            student_name_compact = re.sub(r"\s+", "", student_name_norm)
            student_usn_compact = re.sub(r"\s+", "", student_usn_norm).upper()

            # 1. Exact string match
            if student_name_norm == raw_query or student_usn_norm == raw_query:
                exact_name.append(student)

            # 2. Compact string match (e.g. "user one" / "user 1" -> "user1")
            elif (
                q_compact == student_name_compact
                or q_compact_digits == student_name_compact
                or q_compact_digits.upper() == student_usn_compact
            ):
                compact_matches.append(student)

            # 3. Token subset match
            else:
                student_tokens = set(student_name_norm.split())
                if set(q_tokens).issubset(student_tokens):
                    token_matches.append(student)

        if exact_name:
            matches = exact_name
        elif compact_matches:
            matches = compact_matches
        elif token_matches:
            matches = token_matches

    # ---------------------------------------------------- Fuzzy matching fallback
    if not matches:
        fuzzy_candidates = []
        q_clean = re.sub(r"\b(mark|add|set|put|present|absent|here|attended|usn|roll|number)\b", "", raw_query, flags=re.IGNORECASE).strip()
        q_tokens = [w for w in q_clean.split() if w]

        for student in roster:
            student_name_norm = _normalize_text(student.get("name") or "")
            student_words = [w for w in student_name_norm.split() if len(w) > 1 or len(student_name_norm.split()) == 1]

            best_score = 0.0
            for qt in q_tokens:
                for sw in student_words:
                    ratio = difflib.SequenceMatcher(None, qt, sw).ratio()
                    if ratio > best_score:
                        best_score = ratio

            full_ratio = difflib.SequenceMatcher(None, raw_query, student_name_norm).ratio()
            if full_ratio > best_score:
                best_score = full_ratio

            if best_score >= 0.75:
                fuzzy_candidates.append((best_score, student))

        fuzzy_candidates.sort(key=lambda x: -x[0])
        if fuzzy_candidates:
            top_score = fuzzy_candidates[0][0]
            matches = [c[1] for c in fuzzy_candidates if (top_score - c[0]) <= 0.05]

    # ----------------------------- Build result
    if len(matches) == 0:
        return {"status": "not_found", "matches": [], "parsed": parsed}
    elif len(matches) == 1:
        return {"status": "exact", "matches": matches, "parsed": parsed}
    else:
        return {"status": "multiple", "matches": matches, "parsed": parsed}


# ---------------------------------------------------------------------------
# Continuous Multi-Student Batch Voice Attendance Parser
def _get_surrounding_status(
    transcript: str, s_name: str, s_usn: str, default_status: str = "present"
) -> str:
    """
    Extract status ("present" or "absent") for a specific student from the transcript.
    First checks immediate adjacent words (2 words after then before), then falls back to clause isolation.
    """
    clean_t = _normalize_text(transcript)
    norm_name = _normalize_text(s_name or "")
    norm_first = norm_name.split()[0] if norm_name else ""
    norm_usn = _normalize_text(s_usn or "")

    tokens = clean_t.split()
    target_tokens = [norm_first, norm_name, norm_usn]

    # 1. Check immediate adjacent words (2 words after then before) for status keywords
    for idx, tok in enumerate(tokens):
        if any(
            tt
            and (
                tok == tt
                or (len(tt) >= 3 and difflib.SequenceMatcher(None, tok, tt).ratio() >= 0.78)
            )
            for tt in target_tokens
        ):
            after_words = " ".join(tokens[idx + 1 : idx + 3])
            st_after = _extract_status(after_words)
            if st_after:
                return st_after

            before_words = " ".join(tokens[max(0, idx - 2) : idx])
            st_before = _extract_status(before_words)
            if st_before:
                return st_before

    # 2. Fallback to clause isolation if transcript has commas/newlines
    clauses = re.split(r"[,;\n]|\bband\b", transcript, flags=re.IGNORECASE)
    for clause in clauses:
        clean_c = _normalize_text(clause)
        if not clean_c:
            continue
        if (
            (norm_name and norm_name in clean_c)
            or (norm_first and len(norm_first) >= 3 and norm_first in clean_c)
            or (norm_usn and len(norm_usn) >= 3 and norm_usn in clean_c)
        ):
            st = _extract_status(clean_c)
            if st:
                return st

    return default_status


# ---------------------------------------------------------------------------
# Continuous Multi-Student Batch Voice Attendance Parser
# ---------------------------------------------------------------------------

def parse_batch_transcript(
    full_transcript: str,
    roster: list[dict[str, Any]],
    default_status: str = "present",
    voice_mode: str = "name_status",
) -> dict:
    """
    Parse a continuous multi-student transcript where faculty reads out
    multiple students in sequence. Uses both explicit phrase splitting (commas, status words)
    and full roster scanning to match every spoken student in real time.
    """
    clean_text = _normalize_text(full_transcript)
    text_with_digits = _words_to_digits(clean_text)
    compact_text = re.sub(r"\s+", "", clean_text)
    compact_digits = re.sub(r"\s+", "", text_with_digits)

    transcript_tokens = [t for t in re.split(r"[,\s;\n]+", clean_text) if t]

    marked: list[dict] = []
    ambiguous: list[dict] = []
    not_found: list[str] = []
    seen_student_ids = set()

    # First pass: try chunk-based search if commas / newlines / status words exist
    raw_chunks = re.split(r"[,;\n]|\b(?:present|absent|here|attended)\b", full_transcript, flags=re.IGNORECASE)
    for chunk in raw_chunks:
        phrase = chunk.strip()
        if not phrase or len(phrase) < 2:
            continue

        target_status = default_status
        if voice_mode == "name_status":
            extracted = _extract_status(phrase)
            if extracted:
                target_status = extracted
        elif voice_mode == "bulk_absent":
            target_status = "absent"
        elif voice_mode == "bulk_present":
            target_status = "present"

        search_query = re.sub(r"\b(present|absent|here|attended|not present|mark|student|roll)\b", "", phrase, flags=re.IGNORECASE).strip()
        if not search_query:
            continue

        parsed = parse_transcript(phrase)
        if parsed["type"] == "unknown" or len(parsed["value"]) < 2:
            parsed["value"] = search_query

        res = search_roster(parsed, roster)

        if res["status"] == "exact" and len(res["matches"]) == 1:
            st = res["matches"][0]
            if st["student_id"] not in seen_student_ids:
                seen_student_ids.add(st["student_id"])
                st_copy = dict(st)
                if voice_mode == "name_status":
                    st_copy["target_status"] = _get_surrounding_status(
                        full_transcript, st.get("name") or "", st.get("usn") or "", default_status=target_status
                    )
                else:
                    st_copy["target_status"] = target_status
                marked.append(st_copy)

    # Second pass: Roster-driven continuous scanner across unsegmented text
    for student in roster:
        s_id = student["student_id"]
        if s_id in seen_student_ids:
            continue

        s_name_norm = _normalize_text(student.get("name") or "")
        s_usn_norm = _normalize_text(student.get("usn") or "")
        s_name_compact = re.sub(r"\s+", "", s_name_norm)
        s_usn_compact = re.sub(r"\s+", "", s_usn_norm).upper()

        matched = False

        # Compact / Digits substring match
        if (s_name_compact and (s_name_compact in compact_text or s_name_compact in compact_digits)) or \
           (s_usn_compact and (s_usn_compact in compact_text or s_usn_compact in compact_digits.upper())):
            matched = True

        # Fuzzy token match
        if not matched:
            s_first_name = s_name_norm.split()[0] if s_name_norm else ""
            if len(s_first_name) >= 3:
                for token in transcript_tokens:
                    if len(token) >= 3:
                        ratio = difflib.SequenceMatcher(None, token, s_first_name).ratio()
                        if ratio >= 0.78:
                            matched = True
                            break

        if matched:
            seen_student_ids.add(s_id)
            st_copy = dict(student)
            if voice_mode == "name_status":
                st_copy["target_status"] = _get_surrounding_status(
                    full_transcript, student.get("name") or "", student.get("usn") or "", default_status=default_status
                )
            elif voice_mode == "bulk_absent":
                st_copy["target_status"] = "absent"
            else:
                st_copy["target_status"] = "present"
            marked.append(st_copy)

    return {
        "success": True,
        "marked": marked,
        "ambiguous": ambiguous,
        "not_found": not_found,
        "total_parsed": len(marked) + len(ambiguous) + len(not_found)
    }

