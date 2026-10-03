"""
Station layouts: which wrenches belong to a station and where their torque
points are on that station's chassis picture.

Stored in data/layouts.json (edited from the station page by logged-in line
managers; not in git). On first start it is seeded from layouts.example.json.

    {"stations": {"1": {"image": "chassis-top.svg",
                        "tools": [{"t_no": "T1", "x": 0.18, "y": 0.72, "label": "SG Tightening"}],
                        "updated_by": "manager1", "updated_at": "03-10-2026 11:02:13"}}}

x / y are fractions of the picture's width / height (0..1), so markers stay on
the same bolt at any screen size. A tool without x/y is listed but not placed.
"""
import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("LINE2_DATA_DIR") or os.path.join(HERE, "data")  # override for tests
LAYOUT_FILE = os.path.join(DATA_DIR, "layouts.json")
EXAMPLE_FILE = os.path.join(HERE, "layouts.example.json")
BUILTIN_IMAGE_DIR = os.path.join(HERE, "static", "chassis")
UPLOAD_IMAGE_DIR = os.path.join(DATA_DIR, "chassis")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
UPLOAD_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}  # no SVG uploads: SVG can carry script
MAX_TOOLS_PER_STATION = 60
_T_NO = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}

_lock = threading.Lock()


# ---------------- storage ----------------

def load():
    """Return {station_no: layout_dict}. Never raises; a broken file yields {}."""
    with _lock:
        if not os.path.exists(LAYOUT_FILE) and os.path.exists(EXAMPLE_FILE):
            os.makedirs(DATA_DIR, exist_ok=True)
            shutil.copyfile(EXAMPLE_FILE, LAYOUT_FILE)
        try:
            with open(LAYOUT_FILE, encoding="utf-8") as f:
                raw = json.load(f).get("stations", {})
        except (OSError, ValueError, AttributeError):
            return {}
    return {int(k): v for k, v in raw.items() if str(k).isdigit()}


def save(station, layout, username):
    """Validate and store one station's layout. Returns the stored layout. Raises ValueError."""
    clean = validate(layout)
    clean["updated_by"] = username
    clean["updated_at"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(LAYOUT_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data.setdefault("stations", {})[str(int(station))] = clean
        tmp = LAYOUT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        if os.path.exists(LAYOUT_FILE):
            shutil.copyfile(LAYOUT_FILE, LAYOUT_FILE + ".bak")  # one-step undo by hand
        os.replace(tmp, LAYOUT_FILE)
    return clean


def validate(layout):
    if not isinstance(layout, dict):
        raise ValueError("layout must be an object")
    image = str(layout.get("image") or "")
    if image not in {i["name"] for i in list_images()}:
        raise ValueError(f"unknown chassis image: {image!r}")
    tools_in = layout.get("tools") or []
    if not isinstance(tools_in, list) or len(tools_in) > MAX_TOOLS_PER_STATION:
        raise ValueError(f"tools must be a list of at most {MAX_TOOLS_PER_STATION}")
    tools, seen = [], set()
    for t in tools_in:
        t_no = str((t or {}).get("t_no") or "").strip().upper()
        if not _T_NO.match(t_no):
            raise ValueError(f"invalid wrench number: {t_no!r}")
        if t_no in seen:
            raise ValueError(f"{t_no} is listed twice")
        seen.add(t_no)
        x, y = _fraction(t.get("x")), _fraction(t.get("y"))
        if (x is None) != (y is None):
            x = y = None
        tools.append({"t_no": t_no, "x": x, "y": y, "label": str(t.get("label") or "").strip()[:80]})
    return {"image": image, "tools": tools}


def _fraction(value):
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError("x / y must be numbers between 0 and 1")
    return round(min(1.0, max(0.0, v)), 4)


# ---------------- applying layouts to live data ----------------

def apply(stations, layouts, default_image, add_missing=True):
    """Give every tool its marker position and label from the layout (in place).

    add_missing: also add layout tools the data source doesn't have yet (as PENDING).
    Tools are ordered as in the layout, then any extra tools from the data.
    """
    for number, st in stations.items():
        layout = layouts.get(number, {})
        placed = {t["t_no"].upper(): t for t in layout.get("tools", [])}
        by_tag = {t["tag"].upper(): t for t in st["tools"]}
        ordered = []
        for t_no, lt in placed.items():
            tool = by_tag.pop(t_no, None)
            if tool is None:
                if not add_missing:
                    continue
                tool = {"tag": lt["t_no"], "label": "", "torque_nm": None, "mode": "", "set": None,
                        "actual": None, "status": "PENDING", "updated": None}
            tool["x"], tool["y"] = lt.get("x"), lt.get("y")
            tool["label"] = lt.get("label") or tool.get("label") or tool["tag"]
            ordered.append(tool)
        for tool in by_tag.values():
            tool.setdefault("x", None)
            tool.setdefault("y", None)
            tool["label"] = tool.get("label") or tool["tag"]
            ordered.append(tool)
        st["tools"] = ordered
        st["status"] = "idle" if not ordered else (
            "green" if all(t["status"] == "OK" for t in ordered) else "red")
        st["image"] = layout.get("image") or default_image
        st["layout"] = {"image": st["image"],
                        "tools": [dict(t) for t in layout.get("tools", [])]}
        st["layout_updated"] = (f'{layout["updated_at"]} by {layout["updated_by"]}'
                                if layout.get("updated_at") else None)
    return stations


# ---------------- chassis images ----------------

def list_images():
    images = []
    for folder, kind in ((BUILTIN_IMAGE_DIR, "built-in"), (UPLOAD_IMAGE_DIR, "uploaded")):
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                    images.append({"name": name, "kind": kind})
    return images


def image_path(name):
    """Absolute path of a chassis image by name, or None. Only plain file names are accepted."""
    if not name or name != os.path.basename(name) or name.startswith("."):
        return None
    for folder in (UPLOAD_IMAGE_DIR, BUILTIN_IMAGE_DIR):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def save_upload(filename, data):
    """Store an uploaded chassis picture. Returns its new name. Raises ValueError."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in UPLOAD_EXTENSIONS:
        raise ValueError("upload a PNG, JPG or WEBP picture")
    detected = next((e for magic, e in _MAGIC.items() if data.startswith(magic)), None)
    if detected is None or (detected == ".webp" and data[8:12] != b"WEBP"):
        raise ValueError("file is not a valid PNG, JPG or WEBP picture")
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", os.path.splitext(os.path.basename(filename))[0]).strip("-")[:40]
    name = f"{stem or 'chassis'}-{secrets.token_hex(3)}{detected}"
    os.makedirs(UPLOAD_IMAGE_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_IMAGE_DIR, name), "wb") as f:
        f.write(data)
    return name
