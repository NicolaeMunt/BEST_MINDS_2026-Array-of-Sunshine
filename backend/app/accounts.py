"""Accounts and their parcels. A user registers with name, email, phone and password and gets a session token.
A user's parcels are entered by an administrator (role 'admin', see make_admin.py) from the official land
documents: cadastral number (the parcel's ID), area in ares, the document. Users see their parcels and the demo
ones (owned by the demo user, who cannot sign in). Each parcel is registered with sensors-alerts, which starts a
simulated sensor with that crop's thresholds. Messages are in Romanian, for the page."""
import hashlib
import hmac
import json
import math
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from . import db

SESSION_DAYS = 30
CROPS = ("wheat", "corn", "sunflower", "orchard", "vineyard")  # the crops of sensors-alerts app.crops
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?\d{8,15}$")
CADASTRAL = re.compile(r"^\d[\d.]{3,28}\d$")
MAX_ARI = 10_000_000
# The outline's corners must be in Moldova (a generous box around it); at most this many corners.
MOLDOVA = {"lat": (45.4, 48.5), "lon": (26.6, 30.2)}
MAX_CORNERS = 200
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
        if not user or not user["password_hash"] or not _matches(password or "", user["password_hash"]):
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


# ---------- parcels: the demo ones for everyone, a user's ones entered by an administrator ----------

def _corners(geometry_text):
    """The outline's corners as [lat, lon], without the closing repeat of the first one; [] without an outline."""
    if not geometry_text:
        return []
    ring = json.loads(geometry_text)["coordinates"][0]
    return [[lat, lon] for lon, lat in (ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring)]


def _area_ari(corners):
    """Area of an outline of [lat, lon] corners in ares (shoelace on a local flat projection; fine for a field)."""
    lat0 = math.radians(sum(c[0] for c in corners) / len(corners))
    pts = [(lon * 111_320 * math.cos(lat0), lat * 110_540) for lat, lon in corners]
    twice = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))
    return abs(twice) / 2 / 100


def _polygon(points):
    """[[lat, lon], ...] from the page -> GeoJSON Polygon text ([lon, lat], ring closed), as the satellite job reads."""
    if not isinstance(points, list) or len(points) < 3:
        raise Invalid({"coordinates": "Pune pe hartă cel puțin 3 colțuri ale terenului."})
    if len(points) > MAX_CORNERS:
        raise Invalid({"coordinates": f"Conturul are prea multe puncte: cel mult {MAX_CORNERS}."})
    corners = []
    for p in points:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise Invalid({"coordinates": "Fiecare punct e o pereche lat, lon. Exemplu: 47.3812, 28.8204"})
        if not (MOLDOVA["lat"][0] <= lat <= MOLDOVA["lat"][1] and MOLDOVA["lon"][0] <= lon <= MOLDOVA["lon"][1]):
            raise Invalid({"coordinates": f"Punctul {lat}, {lon} nu e în Moldova. Verifică ordinea: întâi latitudinea (~47), apoi longitudinea (~28)."})
        corners.append([round(lat, 7), round(lon, 7)])
    if corners[0] == corners[-1]:
        corners.pop()
    if len(corners) < 3 or _area_ari(corners) < 1:
        raise Invalid({"coordinates": "Conturul nu închide o suprafață: colțurile nu pot fi pe o singură linie."})
    ring = [[lon, lat] for lat, lon in corners]
    return json.dumps({"type": "Polygon", "coordinates": [ring + ring[:1]]})


def _field_out(row):
    area_ari = row["area_ari"]
    corners = _corners(row["geometry"])
    return {"id": row["id"], "userId": row["user_id"], "name": row["name"], "crop": row["crop"],
            "areaAri": area_ari, "areaHa": None if area_ari is None else round(area_ari / 100, 4),
            "cadastralNumber": row["id"], "location": row["location"], "docType": row["doc_type"],
            "docNumber": row["doc_number"], "docDate": row["doc_date"], "coordinates": corners,
            "outlineAri": round(_area_ari(corners), 1) if corners else None, "createdAt": row["created_at"]}


def _field_input(data):
    """data: name, crop, area_ari, cadastral_number, location, doc_type, doc_number, doc_date (from the document)
    and coordinates, the outline's corners [[lat, lon], ...] (for the map and the satellite)."""
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
    geometry = _polygon(data.get("coordinates"))
    return {"id": cadastral, "name": name, "crop": data["crop"], "area_ari": area, "location": location,
            "doc_type": data["doc_type"], "doc_number": number, "doc_date": when.isoformat(), "geometry": geometry}


# A parcel belongs to a user's account when its owner can sign in (has an email); the others are the demo ones.
_OWNED = "SELECT p.* FROM parcels p JOIN users u ON u.id = p.user_id WHERE u.email IS NOT NULL"


def fields(user_id):
    """The user's parcels, oldest first."""
    with db.get_conn() as conn:
        rows = conn.execute(_OWNED + " AND p.user_id = ? ORDER BY p.created_at, p.id", (user_id,)).fetchall()
    return [_field_out(r) for r in rows]


def account_parcels():
    """Every parcel of a user account, for registering them with sensors-alerts."""
    with db.get_conn() as conn:
        rows = conn.execute(_OWNED + " ORDER BY p.created_at, p.id").fetchall()
    return [_field_out(r) for r in rows]


def visible_parcels(user):
    """[(parcel row, own)]: the user's parcels first, then the demo ones. Other users' parcels are left out."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, u.email IS NOT NULL AS owned FROM parcels p LEFT JOIN users u ON u.id = p.user_id "
            "WHERE u.email IS NULL OR p.user_id = ? ORDER BY owned DESC, p.created_at, p.id",
            (user["id"] if user else -1,)).fetchall()
    return [(r, bool(r["owned"])) for r in rows]


def can_see(parcel_id, user):
    """Demo parcels are for everyone, a user's parcel only for its owner. A parcel the database does not know
    (a deleted one whose simulated sensor still runs) is for nobody."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT p.user_id, u.email FROM parcels p LEFT JOIN users u ON u.id = p.user_id "
                           "WHERE p.id = ?", (parcel_id,)).fetchone()
    return row is not None and (row["email"] is None or (user is not None and row["user_id"] == user["id"]))


def _owned_parcel(conn, parcel_id):
    row = conn.execute(_OWNED + " AND p.id = ?", (parcel_id,)).fetchone()
    if not row:  # unknown, or a demo parcel: those come from backend/data/parcels.geojson
        raise Invalid({"field": "Terenul nu există."}, status=404)
    return row


def add_field(admin_id, user_id, data):
    """A parcel for the user, as written in the document; its cadastral number is its ID everywhere (sensors-alerts,
    readings, alerts). Only administrators call this (see main.py)."""
    values = _field_input(data)
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ? AND email IS NOT NULL", (user_id,)).fetchone():
            raise Invalid({"user": "Utilizatorul nu există."}, status=404)
        if conn.execute("SELECT 1 FROM parcels WHERE id = ?", (values["id"],)).fetchone():
            raise Invalid({"cadastralNumber": "Un teren cu acest număr cadastral e deja înregistrat."}, status=409)
        row = {**values, "user_id": user_id, "crop_confirmed": 1, "ids_fictive": 0, "added_by": admin_id,
               "created_at": db.ts_text(_now())}
        conn.execute(f"INSERT INTO parcels ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
        saved = conn.execute("SELECT * FROM parcels WHERE id = ?", (values["id"],)).fetchone()
    return _field_out(saved)


def update_field(parcel_id, data):
    """Everything but the cadastral number, which is the parcel's ID: a wrong one means deleting and adding again.
    Returns (parcel, whether the outline changed): a new outline needs a new satellite analysis."""
    values = _field_input({**data, "cadastral_number": data.get("cadastral_number") or parcel_id})
    if values.pop("id") != parcel_id:
        raise Invalid({"cadastralNumber": "Numărul cadastral nu se schimbă. Șterge terenul și adaugă-l din nou."})
    with db.get_conn() as conn:
        before = _owned_parcel(conn, parcel_id)
        conn.execute(f"UPDATE parcels SET {', '.join(k + ' = ?' for k in values)} WHERE id = ?",
                     (*values.values(), parcel_id))
        saved = conn.execute("SELECT * FROM parcels WHERE id = ?", (parcel_id,)).fetchone()
    return _field_out(saved), _corners(before["geometry"]) != _corners(saved["geometry"])


def delete_field(parcel_id):
    """Deletes a user's parcel with its stored readings, alerts and satellite results. sensors-alerts cannot forget
    a parcel, so its simulated sensor runs on until that service restarts; the API hides it and stops storing it."""
    with db.get_conn() as conn:
        _owned_parcel(conn, parcel_id)
        for table in ("sensor_readings", "sensor_alerts", "imagery_results", "imagery_warnings", "imagery_skipped"):
            conn.execute(f"DELETE FROM {table} WHERE parcel_id = ?", (parcel_id,))
        conn.execute("DELETE FROM parcels WHERE id = ?", (parcel_id,))


# ---------- administrators ----------

def users(query=""):
    """Every account (not the demo owner), newest first, with the number of parcels and their total area.
    query: part of the name, email or phone."""
    like = "%" + (query or "").strip().lower() + "%"
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT u.*, COUNT(p.id) AS field_count, COALESCE(SUM(p.area_ari), 0) AS total_ari "
            "FROM users u LEFT JOIN parcels p ON p.user_id = u.id WHERE u.email IS NOT NULL "
            "AND (lower(u.name) LIKE ? OR lower(u.email) LIKE ? OR u.phone LIKE ?) "
            "GROUP BY u.id ORDER BY u.id DESC",
            (like, like, "%" + re.sub(r"[\s\-().]", "", query or "") + "%")).fetchall()
    return [{**_user_out(r), "fieldCount": r["field_count"], "totalAri": r["total_ari"]} for r in rows]


def user(user_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND email IS NOT NULL", (user_id,)).fetchone()
    if not row:
        raise Invalid({"user": "Utilizatorul nu există."}, status=404)
    return _user_out(row)


def set_role(email, role):
    """make_admin.py: role 'admin' or 'user' for the account with this email. Returns the user, or None."""
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, (email or "").strip().lower()))
        row = conn.execute("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    return _user_out(row) if row else None
