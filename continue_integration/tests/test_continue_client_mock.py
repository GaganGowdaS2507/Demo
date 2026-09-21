"""
continue_integration/tests/test_continue_client_mock.py

Unit tests for ContinueClient using mock HTTP responses.
No real API calls are made — safe to run without API keys.

Run: python -m pytest tests/ -v
"""

import pytest
from unittest.mock import patch, MagicMock
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.continue_client import ContinueClient, ContinueAPIError


# ─────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("CONTINUE_API_BASE_URL", "https://mock.continue.college.in/api/v1")
    monkeypatch.setenv("CONTINUE_API_KEY",      "test-api-key-12345")
    monkeypatch.setenv("CONTINUE_AUTH_TYPE",    "bearer")
    monkeypatch.setenv("CONTINUE_SYNC_ENABLED", "true")


@pytest.fixture
def client(mock_env):
    return ContinueClient()


# ─────────────────────────────────────────────────────────────
# TEST: mark_attendance — SUCCESS
# ─────────────────────────────────────────────────────────────

def test_mark_attendance_success(client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"id": "ATT-9921", "message": "Attendance recorded"}

    with patch.object(client.session, "post", return_value=mock_response) as mock_post:
        payload = {
            "roll_no":      "1RN22CS001",
            "subject_code": "BCS401",
            "date":         "2026-08-30",
            "period":       2,
            "status":       "present",
            "section":      "CS-3A"
        }
        result = client.mark_attendance(payload)

    assert result["id"] == "ATT-9921"
    mock_post.assert_called_once()


# ─────────────────────────────────────────────────────────────
# TEST: mark_attendance — API ERROR (401 Unauthorized)
# ─────────────────────────────────────────────────────────────

def test_mark_attendance_unauthorized(client):
    mock_response = MagicMock()
    mock_response.ok = False
    mock_response.status_code = 401
    mock_response.json.return_value = {"message": "Invalid API key"}
    mock_response.text = "Unauthorized"

    with patch.object(client.session, "post", return_value=mock_response):
        with pytest.raises(ContinueAPIError) as exc_info:
            client.mark_attendance({"roll_no": "1RN22CS001"})

    assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────
# TEST: get_students — returns list
# ─────────────────────────────────────────────────────────────

def test_get_students_success(client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = [
        {"roll_no": "1RN22CS001", "name": "Rahul Kumar",   "section": "CS-3A"},
        {"roll_no": "1RN22CS002", "name": "Priya Sharma",  "section": "CS-3A"},
        {"roll_no": "1RN22CS003", "name": "Arjun Reddy",   "section": "CS-3A"},
    ]

    with patch.object(client.session, "get", return_value=mock_response):
        students = client.get_students(section="CS-3A")

    assert len(students) == 3
    assert students[0]["roll_no"] == "1RN22CS001"


# ─────────────────────────────────────────────────────────────
# TEST: get_students — empty (section has no students yet)
# ─────────────────────────────────────────────────────────────

def test_get_students_empty(client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = []

    with patch.object(client.session, "get", return_value=mock_response):
        students = client.get_students(section="CS-8Z")

    assert students == []


# ─────────────────────────────────────────────────────────────
# TEST: ping — connected
# ─────────────────────────────────────────────────────────────

def test_ping_success(client):
    mock_response = MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"status": "ok"}

    with patch.object(client.session, "get", return_value=mock_response):
        assert client.ping() is True


# ─────────────────────────────────────────────────────────────
# TEST: ping — unreachable
# ─────────────────────────────────────────────────────────────

def test_ping_failure(client):
    import requests as req
    with patch.object(client.session, "get", side_effect=req.exceptions.ConnectionError):
        assert client.ping() is False


# ─────────────────────────────────────────────────────────────
# TEST: auth header — Bearer
# ─────────────────────────────────────────────────────────────

def test_auth_header_bearer(mock_env, monkeypatch):
    monkeypatch.setenv("CONTINUE_AUTH_TYPE", "bearer")
    client = ContinueClient()
    assert "Authorization" in client.session.headers
    assert client.session.headers["Authorization"].startswith("Bearer ")


# ─────────────────────────────────────────────────────────────
# TEST: auth header — API Key Header
# ─────────────────────────────────────────────────────────────

def test_auth_header_api_key(mock_env, monkeypatch):
    monkeypatch.setenv("CONTINUE_AUTH_TYPE", "api_key_header")
    client = ContinueClient()
    assert "X-API-Key" in client.session.headers
