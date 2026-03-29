from __future__ import annotations

import json
import os
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Generator
from urllib.parse import quote_plus
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import mysql.connector
from flask import Flask, jsonify, redirect, request, send_file, send_from_directory, session
from mysql.connector.cursor import MySQLCursorDict
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
LAGOS_TZ = ZoneInfo("Africa/Lagos")

DEFAULT_AT_RISK_TEMPLATE = "Hey {name}, we haven't seen you in a few days. Stay consistent."
DEFAULT_LOST_TEMPLATE = "Hey {name}, you've been away for a while. Let's get you back on track this week."
DEFAULT_PROMO_TEMPLATE = "Hi {name}, we have a promo running this week. Come in and take advantage."


@dataclass(frozen=True)
class DbConfig:
    host: str = os.getenv("DB_HOST", "127.0.0.1")
    port: int = int(os.getenv("DB_PORT", "3306"))
    user: str = os.getenv("DB_USER", "root")
    password: str = os.getenv("DB_PASSWORD", "")
    database: str = os.getenv("DB_NAME", "retainr")


DB = DbConfig()

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "retainr-dev-secret-change-me")


def lagos_now() -> datetime:
    return datetime.now(LAGOS_TZ)


def lagos_now_naive() -> datetime:
    return lagos_now().replace(tzinfo=None, microsecond=0)


def lagos_today() -> date:
    return lagos_now().date()


@contextmanager
def db_connection(include_database: bool = True) -> Generator[mysql.connector.MySQLConnection, None, None]:
    kwargs: dict[str, Any] = {
        "host": DB.host,
        "port": DB.port,
        "user": DB.user,
        "password": DB.password,
    }
    if include_database:
        kwargs["database"] = DB.database
    conn = mysql.connector.connect(**kwargs)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_cursor(conn: mysql.connector.MySQLConnection) -> Generator[MySQLCursorDict, None, None]:
    cursor = conn.cursor(dictionary=True)
    try:
        yield cursor
    finally:
        cursor.close()


def safe_exec(cursor: MySQLCursorDict, sql: str, params: tuple[Any, ...] | None = None) -> None:
    try:
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
    except mysql.connector.Error:
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
    with db_connection(include_database=False) as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()

    with db_connection() as conn:
        with db_cursor(conn) as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gyms (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    gym_name VARCHAR(180) NOT NULL,
                    owner_name VARCHAR(160) DEFAULT NULL,
                    email VARCHAR(180) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    checkin_token VARCHAR(80) NOT NULL UNIQUE,
                    at_risk_message TEXT DEFAULT NULL,
                    lost_message TEXT DEFAULT NULL,
                    promo_message TEXT DEFAULT NULL,
                    instagram_url VARCHAR(255) DEFAULT NULL,
                    facebook_url VARCHAR(255) DEFAULT NULL,
                    tiktok_url VARCHAR(255) DEFAULT NULL,
                    x_url VARCHAR(255) DEFAULT NULL,
                    website_url VARCHAR(255) DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    gym_id INT NULL,
                    name VARCHAR(120) NOT NULL,
                    phone VARCHAR(30) NOT NULL,
                    phone_normalized VARCHAR(20) DEFAULT NULL,
                    last_visit DATE DEFAULT NULL,
                    expiry_date DATE NOT NULL,
                    monthly_fee DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                    goal VARCHAR(255) DEFAULT NULL,
                    purpose VARCHAR(255) DEFAULT NULL,
                    preferred_time VARCHAR(50) DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_members_gym (gym_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS member_checkins (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    gym_id INT NULL,
                    member_id INT NOT NULL,
                    source VARCHAR(20) NOT NULL DEFAULT 'QR',
                    checkin_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    purpose VARCHAR(255) DEFAULT NULL,
                    session_time VARCHAR(50) DEFAULT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_checkins_gym (gym_id),
                    KEY idx_checkins_member (member_id),
                    KEY idx_checkins_at (checkin_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gym_notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    gym_id INT NOT NULL,
                    member_id INT DEFAULT NULL,
                    kind VARCHAR(50) NOT NULL,
                    message VARCHAR(255) NOT NULL,
                    data_json LONGTEXT DEFAULT NULL,
                    is_read TINYINT(1) NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    KEY idx_notif_gym (gym_id),
                    KEY idx_notif_read (is_read),
                    KEY idx_notif_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

            safe_exec(cursor, "ALTER TABLE members ADD COLUMN gym_id INT NULL")
            safe_exec(cursor, "ALTER TABLE members ADD COLUMN phone_normalized VARCHAR(20) DEFAULT NULL")
            safe_exec(cursor, "ALTER TABLE members ADD COLUMN purpose VARCHAR(255) DEFAULT NULL")
            safe_exec(cursor, "ALTER TABLE members ADD COLUMN preferred_time VARCHAR(50) DEFAULT NULL")
            safe_exec(cursor, "ALTER TABLE members DROP INDEX uq_members_phone_normalized")
            safe_exec(cursor, "ALTER TABLE member_checkins ADD COLUMN gym_id INT NULL")

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
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        "Legacy Gym",
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
                cursor.execute("UPDATE members SET gym_id = %s WHERE gym_id IS NULL OR gym_id = 0", (legacy_gym_id,))
                cursor.execute(
                    """
                    UPDATE member_checkins c
                    JOIN members m ON m.id = c.member_id
                    SET c.gym_id = m.gym_id
                    WHERE c.gym_id IS NULL OR c.gym_id = 0
                    """
                )

            cursor.execute("SELECT id, phone FROM members")
            for row in cursor.fetchall():
                cursor.execute(
                    "UPDATE members SET phone_normalized = %s WHERE id = %s",
                    (normalize_phone(str(row.get("phone") or "")), int(row["id"])),
                )

            safe_exec(cursor, "ALTER TABLE members MODIFY gym_id INT NOT NULL")
            safe_exec(cursor, "ALTER TABLE member_checkins MODIFY gym_id INT NOT NULL")
            safe_exec(cursor, "ALTER TABLE members ADD UNIQUE KEY uq_members_gym_phone (gym_id, phone_normalized)")
            safe_exec(cursor, "ALTER TABLE members ADD KEY idx_members_gym (gym_id)")
            safe_exec(
                cursor,
                "ALTER TABLE members ADD CONSTRAINT fk_members_gym FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE",
            )
            safe_exec(
                cursor,
                "ALTER TABLE member_checkins ADD CONSTRAINT fk_checkins_member FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE CASCADE",
            )
            safe_exec(
                cursor,
                "ALTER TABLE member_checkins ADD CONSTRAINT fk_checkins_gym FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE",
            )
            safe_exec(
                cursor,
                "ALTER TABLE gym_notifications ADD CONSTRAINT fk_notifications_gym FOREIGN KEY (gym_id) REFERENCES gyms(id) ON DELETE CASCADE",
            )
            safe_exec(
                cursor,
                "ALTER TABLE gym_notifications ADD CONSTRAINT fk_notifications_member FOREIGN KEY (member_id) REFERENCES members(id) ON DELETE SET NULL",
            )
        conn.commit()


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
    if path in {"/dashboard", "/members", "/member-form", "/message", "/my-checkin"}:
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
    conn: mysql.connector.MySQLConnection,
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
    conn: mysql.connector.MySQLConnection,
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
    status = status_engine(member_row.get("last_visit"), member_row.get("expiry_date"))
    msg_template = templates["lost"] if status == "Lost" else templates["at_risk"]
    default_message = render_message_template(msg_template, str(member_row.get("name") or ""))
    phone = str(member_row.get("phone") or "")

    return {
        "id": int(member_row["id"]),
        "gym_id": int(member_row["gym_id"]),
        "name": member_row.get("name"),
        "phone": phone,
        "phone_whatsapp": normalize_phone(phone) or "",
        "last_visit": member_row["last_visit"].isoformat() if member_row.get("last_visit") else None,
        "expiry_date": member_row["expiry_date"].isoformat() if member_row.get("expiry_date") else None,
        "monthly_fee": float(member_row.get("monthly_fee") or 0),
        "goal": member_row.get("goal"),
        "purpose": member_row.get("purpose"),
        "preferred_time": member_row.get("preferred_time"),
        "created_at": member_row["created_at"].isoformat() if member_row.get("created_at") else None,
        "status": status,
        "days_inactive": inactive_days(member_row.get("last_visit")),
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
        return jsonify({"ok": False, "error": "Gym name is required."}), 400
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
        return jsonify({"ok": False, "error": "Gym account not found."}), 404

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
                "checkin_at": row["checkin_at"].isoformat() if row.get("checkin_at") else None,
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
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
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
    checkin_qr = "https://api.qrserver.com/v1/create-qr-code/?size=260x260&data=" + quote_plus(checkin_link)

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
        return jsonify({"ok": False, "error": "Gym name is required."}), 400
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
        return jsonify({"ok": False, "error": "Gym not found."}), 404
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
        return jsonify({"ok": False, "error": "Gym not found."}), 404

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
            except mysql.connector.Error as exc:
                if exc.errno == 1062:
                    return jsonify({"ok": False, "error": "Phone already exists for another member in this gym."}), 409
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
        return jsonify({"ok": False, "error": "Gym not found."}), 404
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
            except mysql.connector.Error as exc:
                if exc.errno == 1062:
                    return jsonify({"ok": False, "error": "Phone already exists for another member in this gym."}), 409
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
        return jsonify({"ok": False, "error": "Gym not found."}), 404
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
        return jsonify({"ok": False, "error": "Gym not found."}), 404
    checkin_link = request.host_url.rstrip("/") + "/checkin/" + str(gym["checkin_token"])
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=260x260&data=" + quote_plus(checkin_link)
    return jsonify({"ok": True, "checkin_link": checkin_link, "qr_image_url": qr_url})


@app.get("/api/checkin/qr/download")
def api_checkin_qr_download() -> Any:
    gym_id = current_gym_id()
    if not gym_id:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    gym = fetch_gym_by_id(gym_id)
    if not gym:
        return jsonify({"ok": False, "error": "Gym not found."}), 404

    checkin_link = request.host_url.rstrip("/") + "/checkin/" + str(gym["checkin_token"])
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=600x600&data=" + quote_plus(checkin_link)

    try:
        with urlopen(qr_url, timeout=12) as response:
            qr_binary = response.read()
    except Exception:
        return jsonify({"ok": False, "error": "Unable to generate QR image right now. Please try again."}), 502

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(gym.get("gym_name") or "gym").strip()).strip("_")
    if not safe_name:
        safe_name = "gym"
    filename = f"{safe_name}_checkin_qr.png"
    return send_file(
        BytesIO(qr_binary),
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
                except mysql.connector.Error as exc:
                    if exc.errno == 1062:
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
            "checkin_message": "You're checked in. Have a great workout.",
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
    init_database()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
