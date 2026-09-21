"""
continue_integration/services/continue_client.py

Universal HTTP client for the Continue portal API.

WHY LANGUAGE DOESN'T MATTER:
─────────────────────────────
Continue portal can be built in Java (Spring Boot), PHP (Laravel),
.NET, Node.js, or anything else — it makes ZERO difference to us.
We communicate through standard HTTP REST APIs (JSON over HTTPS).
This is the same as how any mobile app talks to any backend —
the language used internally is invisible to the outside caller.

Our Python `requests` library simply sends HTTP calls:
    POST https://continue.college.in/api/v1/attendance
    Authorization: Bearer <api_key>
    Content-Type: application/json
    Body: { "roll_no": "1RN22CS001", "subject": "BCS401", "status": "present" }

Continue's Java/PHP/.NET server receives it, processes it, responds with JSON.
Python never needs to "know" what language Continue uses internally.
"""

import logging
import requests
from typing import Optional, Dict, Any

# Import from our local config (not from main backend)
from config import (
    CONTINUE_API_BASE_URL,
    CONTINUE_API_KEY,
    AUTH_TYPE,
    API_TIMEOUT_SEC,
    CONTINUE_SYNC_ENABLED,
)

logger = logging.getLogger(__name__)


class ContinueAPIError(Exception):
    """Raised when Continue portal API returns an error."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[Continue API] HTTP {status_code}: {message}")


class ContinueClient:
    """
    Thin HTTP wrapper around the Continue portal REST API.
    Language-agnostic — works regardless of Continue's backend language.

    Usage:
        client = ContinueClient()
        result = client.mark_attendance({...})
    """

    def __init__(self):
        self.base_url = CONTINUE_API_BASE_URL.rstrip("/")
        self.session  = requests.Session()
        self._set_auth_headers()

    def _set_auth_headers(self):
        """Set authentication headers based on AUTH_TYPE in config."""
        if AUTH_TYPE == "bearer":
            self.session.headers.update({
                "Authorization": f"Bearer {CONTINUE_API_KEY}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            })
        elif AUTH_TYPE == "api_key_header":
            # Some APIs use a custom header like X-API-Key
            self.session.headers.update({
                "X-API-Key":    CONTINUE_API_KEY,
                "Content-Type": "application/json",
                "Accept":       "application/json",
            })
        elif AUTH_TYPE == "basic":
            # Basic auth: key = "username:password" base64 encoded
            import base64
            encoded = base64.b64encode(CONTINUE_API_KEY.encode()).decode()
            self.session.headers.update({
                "Authorization": f"Basic {encoded}",
                "Content-Type":  "application/json",
            })
        else:
            logger.warning(f"Unknown AUTH_TYPE: {AUTH_TYPE}. No auth header set.")

    # ─────────────────────────────────────────────────────────
    # ATTENDANCE ENDPOINTS
    # (exact URL paths to be confirmed from Continue API docs)
    # ─────────────────────────────────────────────────────────

    def mark_attendance(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        POST attendance record to Continue portal.
        
        Args:
            payload: dict with attendance data
                     (structure depends on Continue API docs)
        Returns:
            dict: Continue portal's response
        Raises:
            ContinueAPIError: on non-2xx response
        """
        # TODO: Replace "/attendance/mark" with actual endpoint from API docs
        endpoint = "/attendance/mark"
        return self._post(endpoint, payload)

    def mark_attendance_bulk(self, records: list) -> Dict[str, Any]:
        """
        Bulk POST multiple attendance records (if Continue supports it).
        Ask college: "Do you support bulk attendance upload in one request?"
        
        Args:
            records: list of attendance dicts
        Returns:
            dict: Continue portal's response
        """
        # TODO: Confirm bulk endpoint from API docs
        endpoint = "/attendance/bulk"
        return self._post(endpoint, {"records": records})

    # ─────────────────────────────────────────────────────────
    # STUDENT ENDPOINTS
    # ─────────────────────────────────────────────────────────

    def get_students(self, section: Optional[str] = None,
                     department: Optional[str] = None,
                     semester: Optional[int] = None) -> list:
        """
        GET student list from Continue portal.
        
        Args:
            section: filter by section label (e.g. "CS-3A")
            department: filter by dept code (e.g. "CSE")
            semester: filter by semester number
        Returns:
            list of student dicts
        """
        # TODO: Confirm endpoint and query param names from API docs
        params = {}
        if section:
            params["section"] = section
        if department:
            params["department"] = department
        if semester:
            params["semester"] = semester

        endpoint = "/students"
        return self._get(endpoint, params=params)

    def get_student_by_roll(self, roll_no: str) -> Optional[Dict[str, Any]]:
        """
        GET single student by roll number from Continue.
        
        Args:
            roll_no: Student's roll/USN number
        Returns:
            dict: student data or None
        """
        # TODO: Confirm endpoint pattern from API docs
        endpoint = f"/students/{roll_no}"
        try:
            return self._get(endpoint)
        except ContinueAPIError as e:
            if e.status_code == 404:
                return None
            raise

    # ─────────────────────────────────────────────────────────
    # SUBJECT ENDPOINTS  (if Continue exposes subject list)
    # ─────────────────────────────────────────────────────────

    def get_subjects(self, section: Optional[str] = None) -> list:
        """
        GET subject/course list from Continue portal.
        Ask college: "Do you expose a subjects endpoint?"
        """
        # TODO: Confirm from API docs
        params = {}
        if section:
            params["section"] = section
        endpoint = "/subjects"
        return self._get(endpoint, params=params)

    # ─────────────────────────────────────────────────────────
    # TEST CONNECTION
    # ─────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """
        Test if Continue API is reachable and API key is valid.
        Ask college: "Is there a /health or /ping endpoint?"
        """
        try:
            # TODO: Replace with actual health/ping endpoint from API docs
            self._get("/health")
            return True
        except Exception as e:
            logger.error(f"Continue API ping failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # INTERNAL HTTP HELPERS
    # ─────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        logger.debug(f"[Continue] GET {url} params={params}")
        try:
            resp = self.session.get(url, params=params, timeout=API_TIMEOUT_SEC)
            self._raise_for_status(resp)
            return resp.json()
        except requests.RequestException as e:
            raise ContinueAPIError(0, str(e))

    def _post(self, endpoint: str, data: Any) -> Any:
        url = f"{self.base_url}{endpoint}"
        logger.debug(f"[Continue] POST {url} data={data}")
        try:
            resp = self.session.post(url, json=data, timeout=API_TIMEOUT_SEC)
            self._raise_for_status(resp)
            return resp.json()
        except requests.RequestException as e:
            raise ContinueAPIError(0, str(e))

    @staticmethod
    def _raise_for_status(resp: requests.Response):
        if not resp.ok:
            try:
                msg = resp.json().get("message") or resp.text
            except Exception:
                msg = resp.text
            raise ContinueAPIError(resp.status_code, msg)
