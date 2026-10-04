"""Accounts and their fields. A user registers with name, email, phone and password and gets a session token.
Fields are entered by an administrator (role 'admin', see make_admin.py) from the official land documents:
cadastral number, area in ares, the document. Users only see theirs. Each field is registered with
sensors-alerts as parcel F<num>, which starts a simulated sensor with that crop's thresholds.
Messages are in Romanian, for the page."""
import hashlib
import hmac
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from . import db

SESSION_DAYS = 30
CROPS = ("wheat", "barley", "corn", "sunflower", "orchard", "vineyard")
FIELD_ID = re.compile(r"^F(\d+)$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?\d{8,15}$")
CADASTRAL = re.compile(r"^\d[\d.]{3,28}\d$")
MAX_ARI = 10_000_000
# The documents a field can be entered from; the page shows the names.
DOC_TYPES = {
    "titlu": "Titlu de autentificare a dreptului deținătorului de teren",
    "extras": "Extras din Registrul bunurilor imobile",
    "vanzare": "Contract de vânzare-cumpărare",
    "donatie": "Contract de donație",
    "mostenire": "Certificat de moștenitor",
    "arenda": "Contract de arendă",
    "altul": "Alt act",
}
# scrypt cost: about 50 ms per hash, 16 MB of memory.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class Invalid(Exception):
    """What the user typed is not accepted. fields: field name -> message to show next to it."""

    def __init__(self, fields, status=400):
        super().__init__(next(iter(fields.values())))
        self.fields = fields
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def field_id(num):
    return f"F{num}"


def is_field_id(parcel_id):
    """True for the parcels of user fields (F1, F2, ...); the demo sensors of the config are P1, P2, ..."""
    return bool(FIELD_ID.match(parcel_id or ""))


# ---------- checks ----------

def _name(value, what="Numele"):
    value = " ".join((value or "").split())
    if not value:
        raise Invalid({"name": f"{what} lipsește."})
    if len(value) > 80:
        raise Invalid({"name": f"{what} e prea lung: cel mult 80 de caractere."})
    return value


def _email(value):
    value = (value or "").strip()
    if not value:
        raise Invalid({"email": "Scrie adresa de email."})
    if len(value) > 254 or not EMAIL.match(value):
        raise Invalid({"email": "Adresa de email nu arată bine. Exemplu: ion@exemplu.md"})
    return value.lower()


def _phone(value):
    value = re.sub(r"[\s\-().]", "", value or "")
    if not value:
        raise Invalid({"phone": "Scrie numărul de telefon."})
    if not PHONE.match(value):
        raise Invalid({"phone": "Numărul de telefon nu arată bine. Exemplu: +373 69 123 456"})
    return value


def _password(value):
    if len(value or "") < 8:
        raise Invalid({"password": "Parola trebuie să aibă cel puțin 8 caractere."})
    if len(value) > 200:
        raise Invalid({"password": "Parola e prea lungă."})
    return value


def _hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _matches(password, stored):
    try:
        _, salt, _digest = stored.split("$")
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


def _user_out(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"], "phone": row["phone"],
            "role": row["role"], "createdAt": row["created_at"]}


def _email_taken(conn, email, except_id=None):
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    return row is not None and row["id"] != except_id


# ---------- accounts and sessions ----------

def _new_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                 (hashlib.sha256(token.encode()).hexdigest(), user_id, db.ts_text(now),
                  db.ts_text(now + timedelta(days=SESSION_DAYS))))
    return token


def register(name, email, phone, password):
    """New account, signed in: {token, user}."""
    name, email, phone, password = _name(name), _email(email), _phone(phone), _password(password)
    with db.get_conn() as conn:
        if _email_taken(conn, email):
            raise Invalid({"email": "Există deja un cont cu acest email. Intră în cont."}, status=409)
        cur = conn.execute("INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                           (name, email, phone, _hash(password), db.ts_text(_now())))
        token = _new_session(conn, cur.lastrowid)
        user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"token": token, "user": _user_out(user)}


def login(email, password):
    """{token, user}; the same answer for an unknown email and a wrong password."""
    with db.get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
        if not user or not _matches(password or "", user["password_hash"]):
            raise Invalid({"password": "Email sau parolă greșită."}, status=401)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (db.ts_text(_now()),))
        token = _new_session(conn, user["id"])
    return {"token": token, "user": _user_out(user)}


def logout(token):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def user_for_token(token):
    """The signed-in user as a dict, or None for a missing, unknown or expired token."""
    if not token:
        return None
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (hashlib.sha256(token.encode()).hexdigest(), db.ts_text(_now()))).fetchone()
    return _user_out(row) if row else None


def update_profile(user_id, name, email, phone):
    name, email, phone = _name(name), _email(email), _phone(phone)
    with db.get_conn() as conn:
        if _email_taken(conn, email, except_id=user_id):
            raise Invalid({"email": "Acest email e folosit deja de alt cont."}, status=409)
        conn.execute("UPDATE users SET name = ?, email = ?, phone = ? WHERE id = ?", (name, email, phone, user_id))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_out(row)


def change_password(user_id, current, new):
    new = _password(new)
    with db.get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not _matches(current or "", row["password_hash"]):
            raise Invalid({"current": "Parola actuală nu e corectă."})
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_hash(new), user_id))


# ---------- fields: entered by an administrator from the official documents ----------

def _field_out(row):
    area_ari = row["area_ari"]
    return {"id": field_id(row["num"]), "userId": row["user_id"], "name": row["name"], "crop": row["crop"],
            "areaAri": area_ari, "areaHa": None if area_ari is None else round(area_ari / 100, 4),
            "cadastralNumber": row["cadastral_number"], "location": row["location"], "docType": row["doc_type"],
            "docNumber": row["doc_number"], "docDate": row["doc_date"], "createdAt": row["created_at"]}


def _field_input(data):
    """data: name, crop, area_ari, cadastral_number, location, doc_type, doc_number, doc_date (from the document)."""
    name = _name(data.get("name"), "Denumirea terenului")
    if data.get("crop") not in CROPS:
        raise Invalid({"crop": "Alege cultura."})
    try:
        area = round(float(str(data.get("area_ari") or "").replace(",", ".")), 2)
    except ValueError:
        raise Invalid({"areaAri": "Scrie suprafața din act, în ari. Exemplu: 235,5"})
    if not 0 < area <= MAX_ARI:
        raise Invalid({"areaAri": "Suprafața trebuie să fie între 0 și 10 000 000 ari (100 000 ha)."})
    cadastral = re.sub(r"\s", "", data.get("cadastral_number") or "")
    if not cadastral:
        raise Invalid({"cadastralNumber": "Scrie numărul cadastral din act."})
    if not CADASTRAL.match(cadastral):
        raise Invalid({"cadastralNumber": "Numărul cadastral are doar cifre și puncte. Exemplu: 0100415.123"})
    location = " ".join((data.get("location") or "").split())
    if not location:
        raise Invalid({"location": "Scrie localitatea și raionul."})
    if len(location) > 120:
        raise Invalid({"location": "Localitatea e prea lungă: cel mult 120 de caractere."})
    if data.get("doc_type") not in DOC_TYPES:
        raise Invalid({"docType": "Alege tipul actului."})
    number = " ".join((data.get("doc_number") or "").split())
    if not number:
        raise Invalid({"docNumber": "Scrie numărul actului."})
    if len(number) > 60:
        raise Invalid({"docNumber": "Numărul actului e prea lung."})
    try:
        when = date.fromisoformat(data.get("doc_date") or "")
    except ValueError:
        raise Invalid({"docDate": "Scrie data actului."})
    if not date(1990, 1, 1) <= when <= date.today():
        raise Invalid({"docDate": "Data actului trebuie să fie între 1990 și azi."})
    return {"name": name, "crop": data["crop"], "area_ari": area, "cadastral_number": cadastral,
            "location": location, "doc_type": data["doc_type"], "doc_number": number, "doc_date": when.isoformat()}


def _cadastral_taken(conn, cadastral, except_num=None):
    row = conn.execute("SELECT num FROM fields WHERE cadastral_number = ?", (cadastral,)).fetchone()
    if row and row["num"] != except_num:
        raise Invalid({"cadastralNumber": f"Numărul cadastral e deja înregistrat (terenul {field_id(row['num'])})."},
                      status=409)


def fields(user_id):
    """The user's fields, oldest first."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM fields WHERE user_id = ? ORDER BY num", (user_id,)).fetchall()
    return [_field_out(r) for r in rows]


def all_fields():
    """Every user field, for registering them with sensors-alerts."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM fields ORDER BY num").fetchall()
    return [_field_out(r) for r in rows]


def owner(parcel_id):
    """User ID of a field's owner; None for a demo sensor or a deleted field."""
    match = FIELD_ID.match(parcel_id or "")
    if not match:
        return None
    with db.get_conn() as conn:
        row = conn.execute("SELECT user_id FROM fields WHERE num = ?", (int(match[1]),)).fetchone()
    return row["user_id"] if row else None


def can_see(parcel_id, user):
    """Demo sensors are for everyone; a user field only for its owner."""
    return not is_field_id(parcel_id) or (user is not None and owner(parcel_id) == user["id"])


def _num(parcel_id):
    match = FIELD_ID.match(parcel_id or "")
    if not match or owner(parcel_id) is None:
        raise Invalid({"field": "Terenul nu există."}, status=404)
    return int(match[1])


def add_field(admin_id, user_id, data):
    """A field for the user, as written in the document. Only administrators call this (see main.py)."""
    values = _field_input(data)
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise Invalid({"user": "Utilizatorul nu există."}, status=404)
        _cadastral_taken(conn, values["cadastral_number"])
        cur = conn.execute(
            f"INSERT INTO fields (user_id, added_by, created_at, {', '.join(values)}) "
            f"VALUES (?, ?, ?, {', '.join('?' for _ in values)})",
            (user_id, admin_id, db.ts_text(_now()), *values.values()))
        row = conn.execute("SELECT * FROM fields WHERE num = ?", (cur.lastrowid,)).fetchone()
    return _field_out(row)


def update_field(parcel_id, data):
    num = _num(parcel_id)
    values = _field_input(data)
    with db.get_conn() as conn:
        _cadastral_taken(conn, values["cadastral_number"], except_num=num)
        conn.execute(f"UPDATE fields SET {', '.join(k + ' = ?' for k in values)} WHERE num = ?", (*values.values(), num))
        row = conn.execute("SELECT * FROM fields WHERE num = ?", (num,)).fetchone()
    return _field_out(row)


def delete_field(parcel_id):
    """Deletes the field with its stored readings and alerts. sensors-alerts cannot forget a parcel, so its
    simulated sensor runs on until that service restarts; the API hides it and stops storing it."""
    num = _num(parcel_id)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM fields WHERE num = ?", (num,))
        conn.execute("DELETE FROM sensor_readings WHERE parcel_id = ?", (parcel_id,))
        conn.execute("DELETE FROM sensor_alerts WHERE parcel_id = ?", (parcel_id,))


# ---------- administrators ----------

def users(query=""):
    """Every account, newest first, with the number of fields and their total area. query: part of the name,
    email or phone."""
    like = "%" + (query or "").strip().lower() + "%"
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT u.*, COUNT(f.num) AS field_count, COALESCE(SUM(f.area_ari), 0) AS total_ari "
            "FROM users u LEFT JOIN fields f ON f.user_id = u.id "
            "WHERE lower(u.name) LIKE ? OR lower(u.email) LIKE ? OR u.phone LIKE ? "
            "GROUP BY u.id ORDER BY u.id DESC",
            (like, like, "%" + re.sub(r"[\s\-().]", "", query or "") + "%")).fetchall()
    return [{**_user_out(r), "fieldCount": r["field_count"], "totalAri": r["total_ari"]} for r in rows]


def user(user_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise Invalid({"user": "Utilizatorul nu există."}, status=404)
    return _user_out(row)


def set_role(email, role):
    """make_admin.py: role 'admin' or 'user' for the account with this email. Returns the user, or None."""
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, (email or "").strip().lower()))
        row = conn.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    return _user_out(row) if row else None
