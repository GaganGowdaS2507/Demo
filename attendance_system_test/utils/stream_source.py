"""
attendance_system/utils/stream_source.py

Turns whatever an admin/faculty member types into the "camera stream" field
into a full, scheme-qualified URL that cv2.VideoCapture() (and therefore
recognition/stream_manager.FrameGrabber) can open directly.

Previously every form in this app was hard-wired to RTSP only (field name
`rtsp_url`, placeholder "rtsp://192.168.1.100:554/"). Nothing downstream
actually required RTSP though -- cv2.VideoCapture()/FFmpeg happily opens
rtsp://, http://, and https:// sources the exact same way. The only thing
that was RTSP-only was the *input validation and labelling*, not the
streaming pipeline. This module is the single place that turns loose input
into something the pipeline can use, so every entry point (camera registry,
session "assign camera", admin/faculty "start recognition" forms) behaves
the same way.

Accepted inputs, all treated as equivalent:
  - A full URL with scheme:   rtsp://192.168.4.1:554/stream
                              http://192.168.4.1:81/stream
                              https://cam.example.org/live.m3u8
  - A bare IP or hostname:    192.168.4.1
  - host:port                 192.168.4.1:81
  - host/path or host:port/path

Bare host/IP input (no scheme) is assumed to be this project's ESP32-CAM
device, whose bundled firmware always serves MJPEG at port 81, path
/stream (see the ESP32 firmware sketch). The one exception is if the user
supplies the standard RTSP port 554 explicitly, in which case we assume
rtsp:// instead -- that's the one case where "just an IP" is ambiguous.
"""

import re

ALLOWED_SCHEMES = ("rtsp", "http", "https")

# This project's ESP32-CAM firmware always serves MJPEG here (port 81, /stream).
ESP32_DEFAULT_PORT = 81
ESP32_DEFAULT_PATH = "/stream"
RTSP_DEFAULT_PORT = 554

# host[:port][/path...] -- host may be an IPv4 address or a hostname
_HOST_RE = re.compile(
    r"^(?P<host>[A-Za-z0-9](?:[A-Za-z0-9\.\-]*[A-Za-z0-9])?)"
    r"(:(?P<port>\d{1,5}))?"
    r"(?P<path>/.*)?$"
)


class InvalidStreamSource(ValueError):
    """Raised when a user-supplied camera source can't be turned into a usable URL."""
    pass


def normalize_stream_source(raw):
    """
    Normalize a user-typed camera source into a full stream URL.

    Returns:
        - None if `raw` is empty/blank (caller decides whether that's allowed)
        - a full 'scheme://host[:port][/path]' string otherwise

    Raises:
        InvalidStreamSource if `raw` is non-empty but can't be interpreted.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    # Already a full URL (rtsp://, http://, https://, or something else)?
    if "://" in raw:
        scheme, _, rest = raw.partition("://")
        scheme = scheme.strip().lower()
        if scheme not in ALLOWED_SCHEMES:
            raise InvalidStreamSource(
                f"Unsupported stream type '{scheme}://'. "
                f"Use rtsp://, http://, or https://, or just enter the device's IP address."
            )
        host_part = rest.split("/", 1)[0]
        if not host_part:
            raise InvalidStreamSource("Stream URL is missing a host/IP address.")
        return raw

    # No scheme given -- treat as bare host, host:port, or host[:port]/path
    match = _HOST_RE.match(raw)
    if not match or not match.group("host"):
        raise InvalidStreamSource(
            "Enter a full stream URL (rtsp://..., http://..., https://...) "
            "or just the device's IP address, e.g. 192.168.4.1"
        )

    host = match.group("host")
    port = match.group("port")
    path = match.group("path")

    if port and int(port) == RTSP_DEFAULT_PORT:
        return f"rtsp://{host}:{port}{path or '/'}"

    if port:
        return f"http://{host}:{port}{path or ESP32_DEFAULT_PATH}"

    # Bare IP/hostname, no port at all -> assume the ESP32-CAM stream endpoint
    return f"http://{host}:{ESP32_DEFAULT_PORT}{path or ESP32_DEFAULT_PATH}"


def stream_source_help_text():
    """Short help string usable under any 'camera stream' input field."""
    return (
        "Accepts an RTSP, HTTP, or HTTPS stream URL, or just a device IP "
        "address (e.g. 192.168.4.1) -- a bare IP is assumed to be an "
        "ESP32-CAM on this project's default port/path."
    )
