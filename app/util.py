from datetime import datetime, timedelta
import math
import struct

FMT = "%Y-%m-%d %H:%M:%S"


def image_size(path):
    """Read (width, height) for PNG/GIF/JPEG using only stdlib. None if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"\xff\xd8":  # JPEG: walk the marker segments
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    while b == b"\xff":
                        b = f.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg_len - 2, 1)
    except Exception:
        return None
    return None


def safe_filename(value):
    """Reduce a label to a filesystem/Content-Disposition-safe token."""
    cleaned = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in str(value))
    return "_".join(cleaned.split()) or "Export"


def now_str():
    return datetime.now().strftime(FMT)


def parse(ts):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, FMT)
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M")


def duration_seconds(start_ts, end_ts):
    start = parse(start_ts)
    end = parse(end_ts) if end_ts else datetime.now()
    if not start:
        return 0
    return max(0, int((end - start).total_seconds()))


def round_seconds(seconds, rounding_minutes):
    """Round duration UP to the nearest block of `rounding_minutes`."""
    rm = int(rounding_minutes or 0)
    if rm <= 0:
        return seconds
    block = rm * 60
    return int(math.ceil(seconds / block) * block)


def worked_seconds(start_ts, end_ts, paused_seconds=0, pause_started_at=None):
    """Net worked time of a booking: the gross span minus paused time. Handles
    a still-running pause (``pause_started_at`` set) by subtracting the time
    elapsed since the pause began. Open bookings use ``now`` as the end."""
    span = duration_seconds(start_ts, end_ts)
    paused = int(paused_seconds or 0)
    if pause_started_at:
        paused += duration_seconds(pause_started_at, None)
    return max(0, span - paused)


def round_end_ts(start_ts, end_ts, rounding_minutes):
    """Return ``end_ts`` snapped UP so the booking duration is a multiple of
    ``rounding_minutes``. Open bookings (no end) and invalid input pass through
    unchanged. Used when a booking is finished so the stored time, duration and
    amount all stay consistent everywhere."""
    if not end_ts:
        return end_ts
    rm = int(rounding_minutes or 0)
    if rm <= 0:
        return end_ts
    start = parse(start_ts)
    end = parse(end_ts)
    if not start or not end:
        return end_ts
    raw = max(0, int((end - start).total_seconds()))
    rounded = round_seconds(raw, rm)
    if rounded == raw:
        return end_ts
    return (start + timedelta(seconds=rounded)).strftime(FMT)


def fmt_hm(seconds):
    """Compact hours:minutes for tables, e.g. 65 min -> '1:05'."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}:{m:02d}"


def fmt_hm_long(seconds):
    """Spelled-out hours/minutes for PDFs, e.g. '1 Std. 5 Min.', '45 Min.'."""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h and m:
        return f"{h} Std. {m} Min."
    if h:
        return f"{h} Std."
    return f"{m} Min."


def fmt_hms(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_hours(seconds):
    return round(seconds / 3600.0, 2)


def money(value, currency="€"):
    return f"{value:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")
