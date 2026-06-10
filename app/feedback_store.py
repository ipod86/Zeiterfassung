"""Simple plaintext feedback log (bugs + feature requests).

Stored as a human-readable Markdown checklist in ``data/feedback.md`` so it can
be read and ticked off directly in a text editor *and* via the in-app modal.
One entry per line:

    - [ ] #1 [BUG] 2026-06-10 14:32 · David — Beim Stoppen springt die Zeile
    - [x] #2 [WUNSCH] 2026-06-10 15:01 · Anna — Dunkles Theme pro Nutzer

``[ ]`` = offen, ``[x]`` = erledigt. Toggle flips that box.
"""
import re
import threading
from datetime import datetime
from .db import DATA_DIR

FEEDBACK_FILE = DATA_DIR / "feedback.md"
_LOCK = threading.Lock()

_HEADER = (
    "# Feedback — Bugs & Feature-Wünsche\n"
    "# Format: - [ ] #ID [BUG|WUNSCH] JJJJ-MM-TT HH:MM · Nutzer — Text\n"
    "# [ ] = offen, [x] = erledigt. Zum Abhaken einfach x setzen.\n\n"
)

TYPE_LABELS = {"bug": "BUG", "feature": "WUNSCH"}

_LINE_RE = re.compile(
    r"^- \[(?P<done>[ xX])\] #(?P<id>\d+) \[(?P<type>BUG|WUNSCH)\] "
    r"(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d) · (?P<user>.*?) — (?P<msg>.*)$"
)


def _ensure_file():
    if not FEEDBACK_FILE.exists():
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        FEEDBACK_FILE.write_text(_HEADER, encoding="utf-8")


def _parse_lines():
    """Return (header_and_other_lines, [item_dict, ...]) preserving order."""
    _ensure_file()
    raw = FEEDBACK_FILE.read_text(encoding="utf-8").splitlines()
    items = []
    for ln in raw:
        m = _LINE_RE.match(ln)
        if not m:
            continue
        items.append({
            "id": int(m.group("id")),
            "done": m.group("done").lower() == "x",
            "type": m.group("type"),
            "ts": m.group("ts"),
            "user": m.group("user"),
            "message": m.group("msg"),
        })
    return items


def _format_line(item):
    box = "x" if item["done"] else " "
    return (f"- [{box}] #{item['id']} [{item['type']}] {item['ts']} · "
            f"{item['user']} — {item['message']}")


def _write_all(items):
    body = "\n".join(_format_line(i) for i in items)
    FEEDBACK_FILE.write_text(_HEADER + body + ("\n" if body else ""), encoding="utf-8")


def all_items():
    """Open items first (newest first), then done items (newest first)."""
    with _LOCK:
        items = _parse_lines()
    items.sort(key=lambda i: (i["done"], -i["id"]))
    return items


def add(kind, user, message):
    label = TYPE_LABELS.get(kind, "BUG")
    # single line: collapse newlines, strip markdown-breaking chars lightly
    msg = " ".join(str(message).split()).strip()
    if not msg:
        return None
    with _LOCK:
        items = _parse_lines()
        next_id = max((i["id"] for i in items), default=0) + 1
        item = {
            "id": next_id, "done": False, "type": label,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user": (user or "?").replace(" — ", " - "),
            "message": msg.replace(" — ", " - "),
        }
        items.append(item)
        _write_all(items)
    return item


def toggle(item_id, done=None):
    """Flip (or explicitly set) the done flag of one entry. Returns the new state
    or None if not found."""
    with _LOCK:
        items = _parse_lines()
        new_state = None
        for i in items:
            if i["id"] == item_id:
                i["done"] = (not i["done"]) if done is None else bool(done)
                new_state = i["done"]
                break
        if new_state is None:
            return None
        _write_all(items)
    return new_state
