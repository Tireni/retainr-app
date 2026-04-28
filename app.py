from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Generator
from urllib.parse import quote_plus
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

try:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_H
except Exception:  # pragma: no cover - fallback path if dependency is unavailable
    qrcode = None
    ERROR_CORRECT_H = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
LAGOS_TZ = ZoneInfo("Africa/Lagos")

DEFAULT_AT_RISK_TEMPLATE = "Hey {name}, we haven't seen you in a few days. We'd love to have you back soon."
DEFAULT_LOST_TEMPLATE = "Hey {name}, you've been away for a while. We'd love to welcome you back this week."
DEFAULT_PROMO_TEMPLATE = "Hi {name}, we have a special offer running this week. Come in and take advantage."

CHECKIN_STICKER_BG_PRIMARY = os.path.join(STATIC_DIR, "images", "retainrimage.png")
CHECKIN_STICKER_BG_FALLBACK = os.path.join(STATIC_DIR, "images", "retainimage.png")
GYM_LOGO_UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads", "gym_logos")
RESAMPLING = getattr(Image, "Resampling", Image)
QR_DARK_NAVY = (2, 11, 45, 255)  # #020b2d
QR_ELECTRIC_BLUE = (18, 102, 255, 255)  # #1266FF

STICKER_CANVAS_W = 1080
STICKER_CANVAS_H = 1350
STICKER_BRAND_TOP = 70
STICKER_BRAND_QR_GAP = 70
STICKER_FRAME_SIZE = 800
STICKER_FRAME_BORDER = 10
STICKER_FRAME_RADIUS = 42
STICKER_FRAME_PADDING = 28
STICKER_QR_SIZE = 720
STICKER_QR_TO_CTA_GAP = 130
STICKER_SCAN_BOTTOM_MARGIN = 90
STICKER_SCAN_LINE_W = 140
STICKER_SCAN_LINE_H = 5
STICKER_SCAN_GAP = 28

STICKER_FONT_CANDIDATES = [
    os.path.join(STATIC_DIR, "fonts", "Poppins-ExtraBold.ttf"),
    os.path.join(STATIC_DIR, "fonts", "Gilroy-ExtraBold.ttf"),
    os.path.join(STATIC_DIR, "fonts", "Inter-ExtraBold.ttf"),
    os.path.join(BASE_DIR, "assets", "fonts", "Poppins-ExtraBold.ttf"),
    os.path.join(BASE_DIR, "assets", "fonts", "Gilroy-ExtraBold.ttf"),
    os.path.join(BASE_DIR, "assets", "fonts", "Inter-ExtraBold.ttf"),
    "C:/Windows/Fonts/arialbd.ttf",
]

CHECKIN_LAYOUT = {
    "canvas": {"width": 1080, "height": 1600},
    "qr": {"x": 220, "y": 244, "width": 640, "height": 640},
    "logo": None,
}


@dataclass(frozen=True)
class DbConfig:
    path: str = os.getenv("DB_PATH", os.path.join(BASE_DIR, "retainr.sqlite3"))


DB = DbConfig()
sqlite3.register_adapter(Decimal, lambda d: float(d))

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "retainr-dev-secret-change-me")


def lagos_now() -> datetime:
    return datetime.now(LAGOS_TZ)


def lagos_now_naive() -> datetime:
    return lagos_now().replace(tzinfo=None, microsecond=0)


def lagos_today() -> date:
    return lagos_now().date()


@contextmanager
def db_connection(include_database: bool = True) -> Generator[sqlite3.Connection, None, None]:
    del include_database
    db_path = DB.path if os.path.isabs(DB.path) else os.path.join(BASE_DIR, DB.path)
    if db_path != ":memory:":
        dirpath = os.path.dirname(db_path)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_cursor(conn: sqlite3.Connection) -> Generator["DictCursor", None, None]:
    cursor = DictCursor(conn.cursor())
    try:
        yield cursor
    finally:
        cursor.close()


class DictCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @staticmethod
    def _adapt_sql(sql: str) -> str:
        return sql.replace("%s", "?")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None) -> "DictCursor":
        sql_adapted = self._adapt_sql(sql)
        if params is None:
            self._cursor.execute(sql_adapted)
        else:
            self._cursor.execute(sql_adapted, params)
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._cursor.fetchall()]

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid or 0)

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount)

    def close(self) -> None:
        self._cursor.close()


def safe_exec(cursor: DictCursor, sql: str, params: tuple[Any, ...] | None = None) -> None:
    try:
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
    except sqlite3.Error:
        pass


def clean_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def normalize_phone(phone: str, default_country_code: str = "234") -> str | None:
    digits = clean_phone(phone)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and default_country_code:
        digits = default_country_code + digits[1:]
    elif (
        default_country_code
        and not digits.startswith(default_country_code)
        and len(digits) <= 10
    ):
        digits = default_country_code + digits
    return digits if len(digits) >= 8 else None


def random_checkin_token() -> str:
    return secrets.token_urlsafe(24)


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_date(value)
    return None


def to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def first_name(name: str) -> str:
    bits = (name or "").strip().split()
    return bits[0] if bits else "there"


def render_message_template(template: str, member_name: str) -> str:
    return (template or "").replace("{name}", first_name(member_name))


def status_engine(last_visit: date | None, expiry_date: date | None) -> str:
    today = lagos_today()
    if expiry_date and expiry_date < today:
        return "Lost"
    if not last_visit:
        return "At Risk"
    days_off = max(0, (today - last_visit).days)
    if days_off >= 30:
        return "Lost"
    if days_off >= 7:
        return "At Risk"
    if expiry_date and (expiry_date - today).days <= 7:
        return "At Risk"
    return "Active"


def inactive_days(last_visit: date | None) -> int | None:
    if not last_visit:
        return None
    return max(0, (lagos_today() - last_visit).days)


def build_whatsapp_url(phone: str, message_text: str) -> str | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    return f"https://wa.me/{normalized}?text={quote_plus(message_text)}"


def static_url(path: str | None) -> str | None:
    value = str(path or "").strip().replace("\\", "/")
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    value = value.lstrip("/")
    if value.startswith("static/"):
        return "/" + value
    return "/static/" + value


def gym_logo_abs_path(gym_row: dict[str, Any]) -> str | None:
    stored = str(gym_row.get("company_logo_path") or "").strip()
    if not stored:
        return None
    candidate = stored
    if not os.path.isabs(candidate):
        candidate = os.path.join(BASE_DIR, candidate)
    candidate = os.path.abspath(candidate)
    if not os.path.isfile(candidate):
        return None
    return candidate


def remove_managed_logo_file(path: str | None) -> None:
    value = str(path or "").strip()
    if not value:
        return
    abs_path = value if os.path.isabs(value) else os.path.join(BASE_DIR, value)
    abs_path = os.path.abspath(abs_path)
    managed_root = os.path.abspath(GYM_LOGO_UPLOAD_DIR)
    if not abs_path.startswith(managed_root + os.sep):
        return
    if os.path.isfile(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


def resolve_checkin_sticker_background() -> str | None:
    for candidate in (CHECKIN_STICKER_BG_PRIMARY, CHECKIN_STICKER_BG_FALLBACK):
        if os.path.isfile(candidate):
            return candidate
    return None


def load_sticker_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in STICKER_FONT_CANDIDATES:
        if os.path.isfile(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def text_dimensions(font: ImageFont.ImageFont, text: str) -> tuple[int, int]:
    if not text:
        return (0, 0)
    try:
        x0, y0, x1, y1 = font.getbbox(text)
        return (max(0, int(x1 - x0)), max(0, int(y1 - y0)))
    except Exception:
        width = int(font.getlength(text)) if hasattr(font, "getlength") else (len(text) * 10)
        return (max(0, width), int(getattr(font, "size", 16)))


def tracked_text_width(font: ImageFont.ImageFont, text: str, tracking: int = 0) -> int:
    if not text:
        return 0
    total = 0
    for idx, ch in enumerate(text):
        ch_w, _ = text_dimensions(font, ch)
        total += ch_w
        if idx < len(text) - 1:
            total += tracking
    return max(0, total)


def draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: int = 0,
) -> int:
    cursor_x = int(x)
    for idx, ch in enumerate(text):
        draw.text((cursor_x, y), ch, font=font, fill=fill)
        ch_w, _ = text_dimensions(font, ch)
        cursor_x += ch_w
        if idx < len(text) - 1:
            cursor_x += tracking
    return cursor_x


def _draw_rounded_finder(
    draw: ImageDraw.ImageDraw,
    anchor_x: int,
    anchor_y: int,
    module_px: int,
    inset: int,
    dark: tuple[int, int, int, int],
) -> None:
    # 7x7 outer finder, 5x5 white center, 3x3 dark center.
    x0 = anchor_x * module_px
    y0 = anchor_y * module_px
    x1 = x0 + (7 * module_px)
    y1 = y0 + (7 * module_px)
    outer_radius = max(4, int(module_px * 1.8))
    draw.rounded_rectangle(
        (x0 + inset, y0 + inset, x1 - inset, y1 - inset),
        radius=outer_radius,
        fill=dark,
    )

    i1x0 = (anchor_x + 1) * module_px
    i1y0 = (anchor_y + 1) * module_px
    i1x1 = i1x0 + (5 * module_px)
    i1y1 = i1y0 + (5 * module_px)
    inner_white_radius = max(3, int(module_px * 1.35))
    draw.rounded_rectangle(
        (i1x0 + inset, i1y0 + inset, i1x1 - inset, i1y1 - inset),
        radius=inner_white_radius,
        fill=(255, 255, 255, 255),
    )

    i2x0 = (anchor_x + 2) * module_px
    i2y0 = (anchor_y + 2) * module_px
    i2x1 = i2x0 + (3 * module_px)
    i2y1 = i2y0 + (3 * module_px)
    inner_dark_radius = max(3, int(module_px * 1.0))
    draw.rounded_rectangle(
        (i2x0 + inset, i2y0 + inset, i2x1 - inset, i2y1 - inset),
        radius=inner_dark_radius,
        fill=dark,
    )


def fetch_qr_png(checkin_link: str, size: int = 1000) -> Image.Image:
    # Preferred local generator: rounded modules, navy color, H correction, quiet zone >= 4 modules.
    if qrcode is not None and ERROR_CORRECT_H is not None:
        qr_obj = qrcode.QRCode(
            error_correction=ERROR_CORRECT_H,
            border=4,
            box_size=10,
        )
        qr_obj.add_data(checkin_link)
        qr_obj.make(fit=True)
        matrix = qr_obj.get_matrix()
        modules = len(matrix)
        module_px = max(1, int(size // modules))
        canvas_size = modules * module_px
        inset = max(0, int(module_px * 0.04))
        module_radius = max(2, int((module_px - (2 * inset)) * 0.24))

        image = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
        draw = ImageDraw.Draw(image)
        dark = QR_DARK_NAVY

        border = int(getattr(qr_obj, "border", 4) or 4)
        finder_anchors = [
            (border, border),
            (modules - border - 7, border),
            (border, modules - border - 7),
        ]
        finder_cells: set[tuple[int, int]] = set()
        for ax, ay in finder_anchors:
            for yy in range(7):
                for xx in range(7):
                    finder_cells.add((ax + xx, ay + yy))

        for y, row in enumerate(matrix):
            for x, enabled in enumerate(row):
                if not enabled or (x, y) in finder_cells:
                    continue
                px = x * module_px
                py = y * module_px
                draw.rounded_rectangle(
                    (
                        px + inset,
                        py + inset,
                        px + module_px - inset,
                        py + module_px - inset,
                    ),
                    radius=module_radius,
                    fill=dark,
                )

        for ax, ay in finder_anchors:
            _draw_rounded_finder(draw, ax, ay, module_px, inset, dark)

        return image

    # Fallback path if qrcode dependency is unavailable in runtime env.
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=" + str(size) + "x" + str(size) + "&data=" + quote_plus(checkin_link)
    with urlopen(qr_url, timeout=15) as response:
        binary = response.read()
    return Image.open(BytesIO(binary)).convert("RGBA")


def render_checkin_sticker_binary(gym_row: dict[str, Any], checkin_link: str) -> bytes:
    del gym_row
    canvas_w = STICKER_CANVAS_W
    canvas_h = STICKER_CANVAS_H
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    brand_font = load_sticker_font(88)
    scan_font = load_sticker_font(70)
    brand_tracking = -2
    scan_tracking = 1

    brand_left = "Retain"
    brand_right = "r"
    brand_h = text_dimensions(brand_font, "Retainr")[1]
    brand_total_w = tracked_text_width(brand_font, "Retainr", brand_tracking)
    brand_x = (canvas_w - brand_total_w) // 2
    brand_y = STICKER_BRAND_TOP

    next_x = draw_tracked_text(draw, brand_x, brand_y, brand_left, brand_font, QR_DARK_NAVY, brand_tracking)
    next_x += brand_tracking
    draw_tracked_text(draw, next_x, brand_y, brand_right, brand_font, QR_ELECTRIC_BLUE, brand_tracking)

    frame_x = (canvas_w - STICKER_FRAME_SIZE) // 2
    frame_y = brand_y + brand_h + STICKER_BRAND_QR_GAP
    frame_x2 = frame_x + STICKER_FRAME_SIZE
    frame_y2 = frame_y + STICKER_FRAME_SIZE

    draw.rounded_rectangle(
        (frame_x, frame_y, frame_x2, frame_y2),
        radius=STICKER_FRAME_RADIUS,
        fill=(255, 255, 255, 255),
        outline=QR_DARK_NAVY,
        width=STICKER_FRAME_BORDER,
    )

    qr_inner_x = frame_x + STICKER_FRAME_BORDER + STICKER_FRAME_PADDING
    qr_inner_y = frame_y + STICKER_FRAME_BORDER + STICKER_FRAME_PADDING
    qr_inner_size = STICKER_FRAME_SIZE - (2 * (STICKER_FRAME_BORDER + STICKER_FRAME_PADDING))

    qr_img = fetch_qr_png(checkin_link, size=1400)
    qr_fit = ImageOps.contain(qr_img, (STICKER_QR_SIZE, STICKER_QR_SIZE), RESAMPLING.LANCZOS)
    qr_target_x = qr_inner_x + max(0, (qr_inner_size - qr_fit.width) // 2)
    qr_target_y = qr_inner_y + max(0, (qr_inner_size - qr_fit.height) // 2)
    canvas.alpha_composite(qr_fit, (int(qr_target_x), int(qr_target_y)))

    scan_text = "SCAN ME"
    scan_w = tracked_text_width(scan_font, scan_text, scan_tracking)
    scan_h = text_dimensions(scan_font, scan_text)[1]
    scan_y = frame_y2 + STICKER_QR_TO_CTA_GAP
    max_scan_y = canvas_h - STICKER_SCAN_BOTTOM_MARGIN - scan_h
    if scan_y > max_scan_y:
        scan_y = max_scan_y

    row_total_w = STICKER_SCAN_LINE_W + STICKER_SCAN_GAP + scan_w + STICKER_SCAN_GAP + STICKER_SCAN_LINE_W
    row_x = (canvas_w - row_total_w) // 2
    line_y = scan_y + (scan_h - STICKER_SCAN_LINE_H) // 2

    draw.rounded_rectangle(
        (row_x, line_y, row_x + STICKER_SCAN_LINE_W, line_y + STICKER_SCAN_LINE_H),
        radius=999,
        fill=QR_ELECTRIC_BLUE,
    )
    text_x = row_x + STICKER_SCAN_LINE_W + STICKER_SCAN_GAP
    draw_tracked_text(draw, text_x, scan_y, scan_text, scan_font, QR_DARK_NAVY, scan_tracking)
    right_line_x = text_x + scan_w + STICKER_SCAN_GAP
    draw.rounded_rectangle(
        (right_line_x, line_y, right_line_x + STICKER_SCAN_LINE_W, line_y + STICKER_SCAN_LINE_H),
        radius=999,
        fill=QR_ELECTRIC_BLUE,
    )

    out = BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out.getvalue()


def save_uploaded_gym_logo(gym_id: int, file_storage: Any) -> tuple[str, str]:
    if file_storage is None:
        raise ValueError("No logo file provided.")
    os.makedirs(GYM_LOGO_UPLOAD_DIR, exist_ok=True)
    try:
        image = Image.open(file_storage.stream).convert("RGBA")
    except UnidentifiedImageError as exc:
        raise ValueError("Invalid image file. Upload PNG, JPG, or WEBP.") from exc

    max_size = 1800
    if image.width > max_size or image.height > max_size:
        image.thumbnail((max_size, max_size), RESAMPLING.LANCZOS)

    filename = f"gym_{gym_id}_{int(lagos_now().timestamp())}.png"
    abs_path = os.path.join(GYM_LOGO_UPLOAD_DIR, filename)
    image.save(abs_path, format="PNG")
    rel_path = os.path.relpath(abs_path, BASE_DIR).replace("\\", "/")
    return rel_path, abs_path


def gym_templates(gym_row: dict[str, Any]) -> dict[str, str]:
    return {
        "at_risk": str(gym_row.get("at_risk_message") or DEFAULT_AT_RISK_TEMPLATE),
        "lost": str(gym_row.get("lost_message") or DEFAULT_LOST_TEMPLATE),
        "promo": str(gym_row.get("promo_message") or DEFAULT_PROMO_TEMPLATE),
    }


def gym_socials(gym_row: dict[str, Any]) -> dict[str, str | None]:
    return {
        "instagram_url": gym_row.get("instagram_url"),
        "facebook_url": gym_row.get("facebook_url"),
        "tiktok_url": gym_row.get("tiktok_url"),
        "x_url": gym_row.get("x_url"),
        "website_url": gym_row.get("website_url"),
    }


def init_database() -> None:
    def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(r["name"]) == column for r in rows)

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gyms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gym_name TEXT NOT NULL,
                    owner_name TEXT DEFAULT NULL,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    checkin_token TEXT NOT NULL UNIQUE,
                    at_risk_message TEXT DEFAULT NULL,
                    lost_message TEXT DEFAULT NULL,
                    promo_message TEXT DEFAULT NULL,
                    instagram_url TEXT DEFAULT NULL,
                    facebook_url TEXT DEFAULT NULL,
                    tiktok_url TEXT DEFAULT NULL,
                    x_url TEXT DEFAULT NULL,
                    website_url TEXT DEFAULT NULL,
                    company_logo_path TEXT DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gym_id INTEGER,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    phone_normalized TEXT DEFAULT NULL,
                    last_visit DATE DEFAULT NULL,
                    expiry_date DATE NOT NULL,
                    monthly_fee REAL NOT NULL DEFAULT 0.00,
                    goal TEXT DEFAULT NULL,
                    purpose TEXT DEFAULT NULL,
                    preferred_time TEXT DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS member_checkins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gym_id INTEGER,
                    member_id INTEGER NOT NULL,
                    source TEXT NOT NULL DEFAULT 'QR',
                    checkin_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    purpose TEXT DEFAULT NULL,
                    session_time TEXT DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE,
                    FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gym_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gym_id INTEGER NOT NULL,
                    member_id INTEGER DEFAULT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT DEFAULT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE,
                    FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE SET NULL
                )
                """
            )

            if not has_column(conn, "members", "gym_id"):
                safe_exec(cursor, "ALTER TABLE members ADD COLUMN gym_id INTEGER")
            if not has_column(conn, "members", "phone_normalized"):
                safe_exec(cursor, "ALTER TABLE members ADD COLUMN phone_normalized TEXT DEFAULT NULL")
            if not has_column(conn, "members", "purpose"):
                safe_exec(cursor, "ALTER TABLE members ADD COLUMN purpose TEXT DEFAULT NULL")
            if not has_column(conn, "members", "preferred_time"):
                safe_exec(cursor, "ALTER TABLE members ADD COLUMN preferred_time TEXT DEFAULT NULL")
            if not has_column(conn, "member_checkins", "gym_id"):
                safe_exec(cursor, "ALTER TABLE member_checkins ADD COLUMN gym_id INTEGER")
            if not has_column(conn, "gyms", "company_logo_path"):
                safe_exec(cursor, "ALTER TABLE gyms ADD COLUMN company_logo_path TEXT DEFAULT NULL")

            cursor.execute("SELECT COUNT(*) AS cnt FROM gyms")
            gyms_count = int((cursor.fetchone() or {}).get("cnt") or 0)
            cursor.execute("SELECT COUNT(*) AS cnt FROM members")
            members_count = int((cursor.fetchone() or {}).get("cnt") or 0)

            legacy_gym_id: int | None = None
            if gyms_count == 0 and members_count > 0:
                cursor.execute(
                    """
                    INSERT INTO gyms (
                        gym_name, owner_name, email, password_hash, checkin_token,
                        at_risk_message, lost_message, promo_message
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Legacy Business",
                        "Legacy Admin",
                        "legacy@retainr.local",
                        generate_password_hash("legacy12345"),
                        random_checkin_token(),
                        DEFAULT_AT_RISK_TEMPLATE,
                        DEFAULT_LOST_TEMPLATE,
                        DEFAULT_PROMO_TEMPLATE,
                    ),
                )
                legacy_gym_id = int(cursor.lastrowid)
            elif members_count > 0:
                cursor.execute("SELECT id FROM gyms ORDER BY id ASC LIMIT 1")
                row = cursor.fetchone()
                legacy_gym_id = int(row["id"]) if row else None

            if legacy_gym_id:
                cursor.execute("UPDATE members SET gym_id = ? WHERE gym_id IS NULL OR gym_id = 0", (legacy_gym_id,))
                cursor.execute(
                    """
                    UPDATE member_checkins
                    SET gym_id = (
                        SELECT m.gym_id
                        FROM members m
                        WHERE m.id = member_checkins.member_id
                    )
                    WHERE (gym_id IS NULL OR gym_id = 0)
                      AND EXISTS (
                        SELECT 1 FROM members m WHERE m.id = member_checkins.member_id
                    )
                    """
                )

            cursor.execute("SELECT id, phone FROM members")
            for row in cursor.fetchall():
                cursor.execute(
                    "UPDATE members SET phone_normalized = ? WHERE id = ?",
                    (normalize_phone(str(row.get("phone") or "")), int(row["id"])),
                )

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_gym ON members(gym_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkins_gym ON member_checkins(gym_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkins_member ON member_checkins(member_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkins_at ON member_checkins(checkin_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_gym ON gym_notifications(gym_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_read ON gym_notifications(is_read)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_created ON gym_notifications(created_at)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_members_gym_phone ON members(gym_id, phone_normalized)")
        conn.commit()


init_database()


def current_gym_id() -> int | None:
    raw = session.get("retainr_gym_id")
    try:
        gid = int(raw)
    except (TypeError, ValueError):
        return None
    return gid if gid > 0 else None


def is_authenticated() -> bool:
    return current_gym_id() is not None


def is_public_path(path: str) -> bool:
    if path.startswith("/static/"):
        return True
    if path in {
        "/",
        "/login",
        "/register",
        "/admin-login",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",
        "/api/health",
    }:
        return True
    if path == "/checkin" or path.startswith("/checkin/"):
        return True
    if path.startswith("/api/public/checkin/"):
        return True
    return False


def is_protected_path(path: str) -> bool:
    if path in {
        "/dashboard",
        "/members",
        "/member-form",
        "/message",
        "/messages",
        "/social-links",
        "/stickers",
        "/settings",
        "/my-checkin",
    }:
        return True
    if path.startswith("/api/") and not is_public_path(path):
        return True
    return False


def fetch_gym_by_id(gym_id: int) -> dict[str, Any] | None:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM gyms WHERE id = %s LIMIT 1", (gym_id,))
            return cursor.fetchone()


def fetch_gym_by_email(email: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM gyms WHERE email = %s LIMIT 1", (email.lower(),))
            return cursor.fetchone()


def fetch_gym_by_token(token: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM gyms WHERE checkin_token = %s LIMIT 1", (token,))
            return cursor.fetchone()


def fetch_members_for_gym(gym_id: int) -> list[dict[str, Any]]:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM members WHERE gym_id = %s ORDER BY created_at DESC", (gym_id,))
            return cursor.fetchall()


def fetch_member_or_none(gym_id: int, member_id: int) -> dict[str, Any] | None:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("SELECT * FROM members WHERE gym_id = %s AND id = %s LIMIT 1", (gym_id, member_id))
            return cursor.fetchone()


def fetch_member_by_phone(gym_id: int, phone: str) -> dict[str, Any] | None:
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                "SELECT * FROM members WHERE gym_id = %s AND phone_normalized = %s LIMIT 1",
                (gym_id, normalized),
            )
            return cursor.fetchone()


def has_member_checked_in_today(gym_id: int, member_id: int) -> bool:
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM member_checkins
                WHERE gym_id = %s AND member_id = %s AND DATE(checkin_at) = %s
                """,
                (gym_id, member_id, lagos_today()),
            )
            row = cursor.fetchone() or {}
            return int(row.get("cnt") or 0) > 0


def insert_notification(
    conn: sqlite3.Connection,
    gym_id: int,
    kind: str,
    message: str,
    member_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    with db_cursor(conn) as cursor:
        cursor.execute(
            """
            INSERT INTO gym_notifications (gym_id, member_id, kind, message, data_json, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, 0, %s)
            """,
            (
                gym_id,
                member_id,
                kind,
                message,
                json.dumps(data or {}, ensure_ascii=False),
                lagos_now_naive(),
            ),
        )


def log_member_checkin(
    conn: sqlite3.Connection,
    gym_id: int,
    member_id: int,
    source: str,
    purpose: str | None = None,
    session_time: str | None = None,
    visit_date: date | None = None,
) -> None:
    with db_cursor(conn) as cursor:
        cursor.execute(
            """
            INSERT INTO member_checkins (gym_id, member_id, source, checkin_at, purpose, session_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (gym_id, member_id, source, lagos_now_naive(), purpose, session_time),
        )
        cursor.execute(
            """
            UPDATE members
            SET last_visit = %s,
                purpose = COALESCE(%s, purpose),
                preferred_time = COALESCE(%s, preferred_time)
            WHERE id = %s AND gym_id = %s
            """,
            (visit_date or lagos_today(), purpose, session_time, member_id, gym_id),
        )


def parse_member_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    name = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    monthly_fee_raw = str(payload.get("monthly_fee") or "").strip()
    expiry_date = parse_date(payload.get("expiry_date"))
    last_visit = parse_date(payload.get("last_visit"))
    goal = str(payload.get("goal") or "").strip() or None
    purpose = str(payload.get("purpose") or "").strip() or None
    preferred_time = str(payload.get("preferred_time") or "").strip() or None

    if not name:
        return {}, "Name is required."
    if not phone:
        return {}, "Phone is required."
    if not expiry_date:
        return {}, "Expiry date must be valid (YYYY-MM-DD)."
    try:
        monthly_fee = Decimal(monthly_fee_raw)
    except (InvalidOperation, ValueError):
        return {}, "Monthly fee must be a valid number."
    if monthly_fee < 0:
        return {}, "Monthly fee cannot be negative."
    phone_normalized = normalize_phone(phone)
    if not phone_normalized:
        return {}, "Phone number is invalid."

    return {
        "name": name,
        "phone": phone,
        "phone_normalized": phone_normalized,
        "monthly_fee": monthly_fee.quantize(Decimal("0.01")),
        "expiry_date": expiry_date,
        "last_visit": last_visit,
        "goal": goal,
        "purpose": purpose,
        "preferred_time": preferred_time,
    }, None


def member_to_dict(member_row: dict[str, Any], templates: dict[str, str]) -> dict[str, Any]:
    last_visit = to_date(member_row.get("last_visit"))
    expiry_date = to_date(member_row.get("expiry_date"))
    status = status_engine(last_visit, expiry_date)
    msg_template = templates["lost"] if status == "Lost" else templates["at_risk"]
    default_message = render_message_template(msg_template, str(member_row.get("name") or ""))
    phone = str(member_row.get("phone") or "")

    return {
        "id": int(member_row["id"]),
        "gym_id": int(member_row["gym_id"]),
        "name": member_row.get("name"),
        "phone": phone,
        "phone_whatsapp": normalize_phone(phone) or "",
        "last_visit": last_visit.isoformat() if last_visit else None,
        "expiry_date": expiry_date.isoformat() if expiry_date else None,
        "monthly_fee": float(member_row.get("monthly_fee") or 0),
        "goal": member_row.get("goal"),
        "purpose": member_row.get("purpose"),
        "preferred_time": member_row.get("preferred_time"),
        "created_at": to_iso(member_row.get("created_at")),
        "status": status,
        "days_inactive": inactive_days(last_visit),
        "default_message": default_message,
        "whatsapp_url": build_whatsapp_url(phone, default_message),
    }


@app.before_request
def enforce_auth() -> Any:
    path = request.path or "/"
    if is_public_path(path):
        return None
    if not is_protected_path(path):
        return None
    if is_authenticated():
        return None
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Unauthorized. Please login."}), 401
    next_url = request.full_path if request.query_string else path
    return redirect("/login?next=" + quote_plus(next_url))


@app.get("/")
def root() -> Any:
    return redirect("/dashboard" if is_authenticated() else "/login")


@app.get("/login")
def login_page() -> Any:
    if is_authenticated():
        return redirect("/dashboard")
    return send_from_directory(STATIC_DIR, "login.html")


@app.get("/register")
def register_page() -> Any:
    if is_authenticated():
        return redirect("/dashboard")
    return send_from_directory(STATIC_DIR, "register.html")


@app.get("/admin-login")
def legacy_admin_login_redirect() -> Any:
    return redirect("/login")


@app.get("/dashboard")
def dashboard_page() -> Any:
    return send_from_directory(STATIC_DIR, "dashboard.html")


@app.get("/members")
def members_page() -> Any:
    return send_from_directory(STATIC_DIR, "members.html")


@app.get("/member-form")
def member_form_page() -> Any:
    return send_from_directory(STATIC_DIR, "member-form.html")


@app.get("/message")
def message_page() -> Any:
    return send_from_directory(STATIC_DIR, "message.html")


@app.get("/messages")
def messages_page() -> Any:
    return send_from_directory(STATIC_DIR, "messages.html")


@app.get("/social-links")
def social_links_page() -> Any:
    return send_from_directory(STATIC_DIR, "social-links.html")


@app.get("/stickers")
def stickers_page() -> Any:
    return send_from_directory(STATIC_DIR, "stickers.html")


@app.get("/settings")
def settings_page() -> Any:
    return send_from_directory(STATIC_DIR, "settings.html")


@app.get("/my-checkin")
def my_checkin_redirect() -> Any:
    gym = fetch_gym_by_id(current_gym_id() or 0)
    if not gym:
        return redirect("/login")
    return redirect("/checkin/" + str(gym["checkin_token"]))


@app.get("/checkin")
@app.get("/checkin/<token>")
def checkin_page(token: str | None = None) -> Any:
    return send_from_directory(STATIC_DIR, "checkin.html")


@app.get("/api/health")
def api_health() -> Any:
    return jsonify({"ok": True, "service": "retainr"})


@app.post("/api/auth/register")
def api_auth_register() -> Any:
    payload = request.get_json(silent=True) or {}
    gym_name = str(payload.get("gym_name") or "").strip()
    owner_name = str(payload.get("owner_name") or "").strip() or None
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not gym_name:
        return jsonify({"ok": False, "error": "Business name is required."}), 400
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Valid email is required."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "Password must be at least 6 characters."}), 400
    if fetch_gym_by_email(email):
        return jsonify({"ok": False, "error": "Email is already registered."}), 409

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                INSERT INTO gyms (
                    gym_name, owner_name, email, password_hash, checkin_token,
                    at_risk_message, lost_message, promo_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    gym_name,
                    owner_name,
                    email,
                    generate_password_hash(password),
                    random_checkin_token(),
                    DEFAULT_AT_RISK_TEMPLATE,
                    DEFAULT_LOST_TEMPLATE,
                    DEFAULT_PROMO_TEMPLATE,
                ),
            )
            conn.commit()
            gym_id = int(cursor.lastrowid)
    session["retainr_gym_id"] = gym_id
    session["retainr_gym_name"] = gym_name
    return jsonify({"ok": True, "next": "/dashboard"})


@app.post("/api/auth/login")
def api_auth_login() -> Any:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    next_url = str(payload.get("next") or "/dashboard").strip() or "/dashboard"
    if not next_url.startswith("/") or next_url.startswith("//") or next_url.startswith("/api/"):
        next_url = "/dashboard"

    gym = fetch_gym_by_email(email)
    if not gym or not check_password_hash(str(gym["password_hash"]), password):
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401
    session["retainr_gym_id"] = int(gym["id"])
    session["retainr_gym_name"] = str(gym["gym_name"])
    return jsonify({"ok": True, "next": next_url})


@app.post("/api/auth/logout")
def api_auth_logout() -> Any:
    session.pop("retainr_gym_id", None)
    session.pop("retainr_gym_name", None)
    return jsonify({"ok": True})


@app.get("/api/dashboard")
def api_dashboard() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business account not found."}), 404

    templates = gym_templates(gym)
    members_raw = fetch_members_for_gym(gym_id)
    members = [member_to_dict(row, templates) for row in members_raw]
    members_map = {m["id"]: m for m in members}

    attention_needed = [m for m in members if m["status"] in {"At Risk", "Lost"}]
    attention_needed.sort(key=lambda m: (m["status"] != "Lost", -(m["days_inactive"] or 0)))

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                SELECT c.id, c.member_id, c.source, c.checkin_at, c.purpose, c.session_time
                FROM member_checkins c
                WHERE c.gym_id = %s
                ORDER BY c.checkin_at DESC
                LIMIT 10
                """,
                (gym_id,),
            )
            recent_raw = cursor.fetchall()
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM member_checkins WHERE gym_id = %s AND DATE(checkin_at) = %s",
                (gym_id, lagos_today()),
            )
            today_checkins = int((cursor.fetchone() or {}).get("cnt") or 0)
            cursor.execute(
                """
                SELECT id, member_id, kind, message, data_json, is_read, created_at
                FROM gym_notifications
                WHERE gym_id = %s
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (gym_id,),
            )
            notifications_raw = cursor.fetchall()

    recent_checkins: list[dict[str, Any]] = []
    for row in recent_raw:
        member = members_map.get(int(row["member_id"]))
        recent_checkins.append(
            {
                "id": int(row["id"]),
                "member_id": int(row["member_id"]),
                "name": member["name"] if member else "Unknown",
                "source": row.get("source"),
                "purpose": row.get("purpose"),
                "session_time": row.get("session_time"),
                "checkin_at": to_iso(row.get("checkin_at")),
            }
        )

    notifications: list[dict[str, Any]] = []
    for row in notifications_raw:
        member = members_map.get(int(row["member_id"])) if row.get("member_id") else None
        try:
            data_json = json.loads(str(row.get("data_json") or "{}"))
            if not isinstance(data_json, dict):
                data_json = {}
        except json.JSONDecodeError:
            data_json = {}
        notifications.append(
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "message": row["message"],
                "member_id": int(row["member_id"]) if row.get("member_id") else None,
                "member_name": member["name"] if member else None,
                "is_read": bool(row.get("is_read")),
                "created_at": to_iso(row.get("created_at")),
                "data": data_json,
            }
        )

    for member in attention_needed[:8]:
        notifications.append(
            {
                "id": None,
                "kind": "MESSAGE_NEEDED",
                "message": f"{member['name']} is {member['status']} and needs outreach.",
                "member_id": member["id"],
                "member_name": member["name"],
                "is_read": False,
                "created_at": lagos_now_naive().isoformat(),
                "data": {"status": member["status"]},
            }
        )

    origin = request.host_url.rstrip("/")
    checkin_link = origin + "/checkin/" + str(gym["checkin_token"])
    checkin_qr = "/api/checkin/qr/image?v=" + quote_plus(str(lagos_now_naive().isoformat()))
    company_logo_url = static_url(gym.get("company_logo_path"))

    return jsonify(
        {
            "ok": True,
            "gym": {
                "id": int(gym["id"]),
                "gym_name": gym["gym_name"],
                "owner_name": gym.get("owner_name"),
                "email": gym["email"],
                "checkin_token": gym["checkin_token"],
                "checkin_link": checkin_link,
                "checkin_qr_image_url": checkin_qr,
                "company_logo_url": company_logo_url,
                "has_company_logo": bool(company_logo_url),
                "templates": templates,
                "socials": gym_socials(gym),
            },
            "stats": {
                "total_members": len(members),
                "active_members": sum(1 for m in members if m["status"] == "Active"),
                "at_risk_members": sum(1 for m in members if m["status"] == "At Risk"),
                "lost_members": sum(1 for m in members if m["status"] == "Lost"),
                "revenue_at_risk": round(sum(float(m["monthly_fee"]) for m in members if m["status"] == "Lost"), 2),
                "today_checkins": today_checkins,
            },
            "members": members,
            "attention_needed": attention_needed,
            "recent_checkins": recent_checkins,
            "notifications": notifications,
        }
    )


@app.put("/api/gym/settings")
def api_gym_settings() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    gym_name = str(payload.get("gym_name") or "").strip()
    owner_name = str(payload.get("owner_name") or "").strip() or None
    instagram_url = str(payload.get("instagram_url") or "").strip() or None
    facebook_url = str(payload.get("facebook_url") or "").strip() or None
    tiktok_url = str(payload.get("tiktok_url") or "").strip() or None
    x_url = str(payload.get("x_url") or "").strip() or None
    website_url = str(payload.get("website_url") or "").strip() or None
    if not gym_name:
        return jsonify({"ok": False, "error": "Business name is required."}), 400
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                UPDATE gyms
                SET gym_name = %s, owner_name = %s, instagram_url = %s, facebook_url = %s, tiktok_url = %s, x_url = %s, website_url = %s
                WHERE id = %s
                """,
                (gym_name, owner_name, instagram_url, facebook_url, tiktok_url, x_url, website_url, gym_id),
            )
        conn.commit()
    session["retainr_gym_name"] = gym_name
    return jsonify({"ok": True})


@app.post("/api/gym/logo")
def api_gym_logo_upload() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404
    upload = request.files.get("logo")
    if upload is None or not str(upload.filename or "").strip():
        return jsonify({"ok": False, "error": "Select a logo image to upload."}), 400

    try:
        rel_path, _ = save_uploaded_gym_logo(gym_id, upload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "Unable to process logo image."}), 500

    old_path = str(gym.get("company_logo_path") or "").strip()

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("UPDATE gyms SET company_logo_path = %s WHERE id = %s", (rel_path, gym_id))
        conn.commit()

    if old_path:
        old_abs_path = old_path if os.path.isabs(old_path) else os.path.join(BASE_DIR, old_path)
        new_abs_path = os.path.join(BASE_DIR, rel_path)
        if os.path.abspath(old_abs_path) != os.path.abspath(new_abs_path):
            remove_managed_logo_file(old_path)

    return jsonify({"ok": True, "company_logo_url": static_url(rel_path)})


@app.delete("/api/gym/logo")
def api_gym_logo_delete() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404

    old_path = str(gym.get("company_logo_path") or "").strip()
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("UPDATE gyms SET company_logo_path = NULL WHERE id = %s", (gym_id,))
        conn.commit()

    if old_path:
        remove_managed_logo_file(old_path)

    return jsonify({"ok": True})


@app.put("/api/messages/templates")
def api_messages_templates() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    at_risk_message = str(payload.get("at_risk_message") or "").strip() or DEFAULT_AT_RISK_TEMPLATE
    lost_message = str(payload.get("lost_message") or "").strip() or DEFAULT_LOST_TEMPLATE
    promo_message = str(payload.get("promo_message") or "").strip() or DEFAULT_PROMO_TEMPLATE
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                "UPDATE gyms SET at_risk_message = %s, lost_message = %s, promo_message = %s WHERE id = %s",
                (at_risk_message, lost_message, promo_message, gym_id),
            )
        conn.commit()
    return jsonify({"ok": True})


@app.post("/api/messages/link")
def api_messages_link() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    member_id = int(payload.get("member_id") or 0)
    template_type = str(payload.get("template_type") or "status").strip().lower()
    custom_message = str(payload.get("message") or "").strip()

    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404
    member = fetch_member_or_none(gym_id, member_id)
    if not member:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    templates = gym_templates(gym)
    status = status_engine(member.get("last_visit"), member.get("expiry_date"))

    if custom_message:
        msg = custom_message
    elif template_type == "promo":
        msg = render_message_template(templates["promo"], str(member["name"]))
    elif template_type == "lost":
        msg = render_message_template(templates["lost"], str(member["name"]))
    elif template_type == "at_risk":
        msg = render_message_template(templates["at_risk"], str(member["name"]))
    else:
        msg = render_message_template(templates["lost"] if status == "Lost" else templates["at_risk"], str(member["name"]))

    url = build_whatsapp_url(str(member["phone"]), msg)
    if not url:
        return jsonify({"ok": False, "error": "Member has invalid phone number."}), 400
    return jsonify({"ok": True, "whatsapp_url": url, "message": msg})


@app.post("/api/notifications/mark-all-read")
def api_notifications_mark_all_read() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("UPDATE gym_notifications SET is_read = 1 WHERE gym_id = %s AND is_read = 0", (gym_id,))
        conn.commit()
    return jsonify({"ok": True})


@app.get("/api/members")
def api_members() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404

    status_filter = str(request.args.get("status", "all")).strip().lower()
    query = str(request.args.get("q", "")).strip().lower()
    rows = fetch_members_for_gym(gym_id)
    members = [member_to_dict(row, gym_templates(gym)) for row in rows]
    if status_filter in {"active", "at risk", "lost"}:
        members = [m for m in members if m["status"] == status_filter.title()]
    if query:
        members = [m for m in members if query in str(m["name"]).lower() or query in str(m["phone"]).lower()]
    return jsonify({"ok": True, "items": members, "count": len(members)})


@app.post("/api/members")
def api_create_member() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    parsed, error = parse_member_payload(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO members (
                        gym_id, name, phone, phone_normalized, last_visit, expiry_date, monthly_fee, goal, purpose, preferred_time
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        gym_id,
                        parsed["name"],
                        parsed["phone"],
                        parsed["phone_normalized"],
                        parsed["last_visit"],
                        parsed["expiry_date"],
                        parsed["monthly_fee"],
                        parsed["goal"],
                        parsed["purpose"],
                        parsed["preferred_time"],
                    ),
                )
                conn.commit()
                member_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed" in str(exc):
                    return jsonify({"ok": False, "error": "Phone already exists for another member in this business."}), 409
                raise
    gym = fetch_gym_by_id(gym_id) or {}
    member = fetch_member_or_none(gym_id, member_id)
    return jsonify({"ok": True, "member": member_to_dict(member, gym_templates(gym)) if member else None}), 201


@app.get("/api/members/<int:member_id>")
def api_get_member(member_id: int) -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404
    member = fetch_member_or_none(gym_id, member_id)
    if not member:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    return jsonify({"ok": True, "member": member_to_dict(member, gym_templates(gym))})


@app.put("/api/members/<int:member_id>")
def api_update_member(member_id: int) -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    if not fetch_member_or_none(gym_id, member_id):
        return jsonify({"ok": False, "error": "Member not found."}), 404
    payload = request.get_json(silent=True) or {}
    parsed, error = parse_member_payload(payload)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            try:
                cursor.execute(
                    """
                    UPDATE members
                    SET name = %s, phone = %s, phone_normalized = %s, last_visit = %s, expiry_date = %s,
                        monthly_fee = %s, goal = %s, purpose = %s, preferred_time = %s
                    WHERE id = %s AND gym_id = %s
                    """,
                    (
                        parsed["name"],
                        parsed["phone"],
                        parsed["phone_normalized"],
                        parsed["last_visit"],
                        parsed["expiry_date"],
                        parsed["monthly_fee"],
                        parsed["goal"],
                        parsed["purpose"],
                        parsed["preferred_time"],
                        member_id,
                        gym_id,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint failed" in str(exc):
                    return jsonify({"ok": False, "error": "Phone already exists for another member in this business."}), 409
                raise
    gym = fetch_gym_by_id(gym_id) or {}
    updated = fetch_member_or_none(gym_id, member_id)
    return jsonify({"ok": True, "member": member_to_dict(updated, gym_templates(gym)) if updated else None})


@app.delete("/api/members/<int:member_id>")
def api_delete_member(member_id: int) -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("DELETE FROM members WHERE gym_id = %s AND id = %s", (gym_id, member_id))
            conn.commit()
            deleted = cursor.rowcount > 0
    if not deleted:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    return jsonify({"ok": True})


@app.post("/api/members/<int:member_id>/mark-visit")
def api_mark_visit(member_id: int) -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    member = fetch_member_or_none(gym_id, member_id)
    if not member:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    payload = request.get_json(silent=True) or {}
    visit_date = parse_date(payload.get("visit_date")) or lagos_today()
    duplicate_today = visit_date == lagos_today() and has_member_checked_in_today(gym_id, member_id)
    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute("UPDATE members SET last_visit = %s WHERE id = %s AND gym_id = %s", (visit_date, member_id, gym_id))
        if not duplicate_today:
            log_member_checkin(conn, gym_id, member_id, "MANUAL", visit_date=visit_date)
            insert_notification(
                conn,
                gym_id,
                "CHECKIN",
                f"{member['name']} checked in manually.",
                member_id=member_id,
                data={"source": "MANUAL"},
            )
        conn.commit()
    gym = fetch_gym_by_id(gym_id) or {}
    updated = fetch_member_or_none(gym_id, member_id)
    return jsonify(
        {
            "ok": True,
            "member": member_to_dict(updated, gym_templates(gym)) if updated else None,
            "already_checked_in_today": duplicate_today,
        }
    )


@app.get("/api/members/<int:member_id>/message")
def api_member_message(member_id: int) -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404
    member = fetch_member_or_none(gym_id, member_id)
    if not member:
        return jsonify({"ok": False, "error": "Member not found."}), 404
    member_view = member_to_dict(member, gym_templates(gym))
    msg = member_view["default_message"]
    return jsonify(
        {
            "ok": True,
            "member": member_view,
            "message": msg,
            "whatsapp_url": build_whatsapp_url(str(member["phone"]), msg),
            "phone_whatsapp": member_view["phone_whatsapp"],
        }
    )


@app.get("/api/checkin/qr")
def api_checkin_qr() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404
    checkin_link = request.host_url.rstrip("/") + "/checkin/" + str(gym["checkin_token"])
    qr_url = "/api/checkin/qr/image?v=" + quote_plus(str(lagos_now_naive().isoformat()))
    return jsonify({"ok": True, "checkin_link": checkin_link, "qr_image_url": qr_url})


@app.get("/api/checkin/qr/image")
def api_checkin_qr_image() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404

    checkin_link = request.host_url.rstrip("/") + "/checkin/" + str(gym["checkin_token"])
    try:
        sticker_binary = render_checkin_sticker_binary(gym, checkin_link)
    except Exception:
        return jsonify({"ok": False, "error": "Unable to generate QR image right now. Please try again."}), 502

    return send_file(
        BytesIO(sticker_binary),
        mimetype="image/png",
        as_attachment=False,
        download_name="checkin_qr_preview.png",
        max_age=0,
    )


@app.get("/api/checkin/qr/download")
def api_checkin_qr_download() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Business not found."}), 404

    checkin_link = request.host_url.rstrip("/") + "/checkin/" + str(gym["checkin_token"])
    try:
        sticker_binary = render_checkin_sticker_binary(gym, checkin_link)
    except Exception:
        return jsonify({"ok": False, "error": "Unable to generate QR image right now. Please try again."}), 502

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(gym.get("gym_name") or "business").strip()).strip("_")
    if not safe_name:
        safe_name = "business"
    filename = f"{safe_name}_checkin_qr_sticker.png"
    return send_file(
        BytesIO(sticker_binary),
        mimetype="image/png",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )


@app.get("/api/public/checkin/context")
@app.get("/api/public/checkin/context/<token>")
def api_public_checkin_context(token: str | None = None) -> Any:
    token_final = token or str(request.args.get("t") or "").strip()
    if not token_final:
        return jsonify({"ok": False, "error": "Check-in token is missing."}), 400
    gym = fetch_gym_by_token(token_final)
    if not gym:
        return jsonify({"ok": False, "error": "Invalid check-in link."}), 404
    return jsonify(
        {
            "ok": True,
            "gym": {
                "gym_name": gym["gym_name"],
                "owner_name": gym.get("owner_name"),
                "token": gym["checkin_token"],
                "socials": gym_socials(gym),
            },
        }
    )


@app.post("/api/public/checkin/lookup")
def api_public_checkin_lookup() -> Any:
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()
    phone_raw = str(payload.get("phone") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Check-in token is required."}), 400
    gym = fetch_gym_by_token(token)
    if not gym:
        return jsonify({"ok": False, "error": "Invalid check-in link."}), 404
    gym_id = int(gym["id"])
    normalized = normalize_phone(phone_raw)
    if not normalized:
        return jsonify({"ok": False, "error": "Enter a valid phone number."}), 400
    member = fetch_member_by_phone(gym_id, phone_raw)
    if not member:
        return jsonify({"ok": True, "exists": False, "checked_in_today": False, "phone_normalized": normalized})
    member_view = member_to_dict(member, gym_templates(gym))
    return jsonify(
        {
            "ok": True,
            "exists": True,
            "checked_in_today": has_member_checked_in_today(gym_id, int(member["id"])),
            "phone_normalized": normalized,
            "member": member_view,
        }
    )


@app.post("/api/public/checkin/submit")
def api_public_checkin_submit() -> Any:
    payload = request.get_json(silent=True) or {}
    token = str(payload.get("token") or "").strip()
    phone_raw = str(payload.get("phone") or "").strip()
    name = str(payload.get("name") or "").strip()
    goal = str(payload.get("goal") or "").strip() or None
    purpose = str(payload.get("purpose") or "").strip() or None
    session_time = str(payload.get("session_time") or "").strip() or None
    if not token:
        return jsonify({"ok": False, "error": "Check-in token is required."}), 400
    gym = fetch_gym_by_token(token)
    if not gym:
        return jsonify({"ok": False, "error": "Invalid check-in link."}), 404
    gym_id = int(gym["id"])
    normalized = normalize_phone(phone_raw)
    if not normalized:
        return jsonify({"ok": False, "error": "Enter a valid phone number."}), 400

    existing = fetch_member_by_phone(gym_id, phone_raw)
    if existing and has_member_checked_in_today(gym_id, int(existing["id"])):
        with db_connection() as conn:
            insert_notification(
                conn,
                gym_id,
                "DUPLICATE_CHECKIN",
                f"{existing['name']} attempted a second check-in today.",
                member_id=int(existing["id"]),
                data={"source": "QR"},
            )
            conn.commit()
        return jsonify({"ok": False, "error": "You have already checked in today.", "already_checked_in_today": True}), 409

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            if existing:
                member_id = int(existing["id"])
                mode = "existing"
            else:
                if not name:
                    return jsonify({"ok": False, "error": "Full name is required for new members."}), 400
                try:
                    cursor.execute(
                        """
                        INSERT INTO members (
                            gym_id, name, phone, phone_normalized, last_visit, expiry_date, monthly_fee, goal, purpose, preferred_time
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            gym_id,
                            name,
                            phone_raw,
                            normalized,
                            lagos_today(),
                            lagos_today() + timedelta(days=30),
                            Decimal("0.00"),
                            goal,
                            purpose,
                            session_time,
                        ),
                    )
                    member_id = int(cursor.lastrowid)
                except sqlite3.IntegrityError as exc:
                    if "UNIQUE constraint failed" in str(exc):
                        concurrent = fetch_member_by_phone(gym_id, phone_raw)
                        if not concurrent:
                            raise
                        member_id = int(concurrent["id"])
                    else:
                        raise
                mode = "new"

        log_member_checkin(conn, gym_id, member_id, "QR", purpose=purpose, session_time=session_time)
        member_after = fetch_member_or_none(gym_id, member_id)
        insert_notification(
            conn,
            gym_id,
            "CHECKIN",
            f"{(member_after or {}).get('name', 'A member')} checked in via QR.",
            member_id=member_id,
            data={"source": "QR", "mode": mode},
        )
        conn.commit()

    member_after = fetch_member_or_none(gym_id, member_id)
    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "member": member_to_dict(member_after, gym_templates(gym)) if member_after else None,
            "checkin_message": "You're checked in. Have a great session.",
        }
    )


@app.errorhandler(404)
def page_not_found(_: Exception) -> Any:
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found."}), 404
    return redirect("/dashboard" if is_authenticated() else "/login")


@app.errorhandler(500)
def internal_error(_: Exception) -> Any:
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Internal server error."}), 500
    return jsonify({"ok": False, "error": "Internal server error."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
