"""Comptes et projets, stockés en local (SQLite) : rien ne sort du PC (NFR-01).

Sécurité des comptes :
- mot de passe haché avec scrypt (sel aléatoire de 16 octets par compte), jamais stocké en clair ;
- comparaison en temps constant (hmac.compare_digest) ;
- « mot de passe oublié » sans e-mail (application locale) : un code de secours est
  affiché une seule fois à l'inscription ; il permet de choisir un nouveau mot de passe ;
  il est lui aussi stocké haché, et renouvelé après usage ;
- verrouillage temporaire après plusieurs échecs de connexion.
Chaque utilisateur ne voit que ses projets ; leurs fichiers sont dans output/users/<id>/.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import config

DB_PATH = config.ROOT_DIR / "data" / "smartdeck.db"
USERS_DIR = config.OUTPUT_DIR / "users"
MIN_PASSWORD = 8
MAX_FAILURES, LOCK_SECONDS = 5, 300
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_PREFS = {"language": None, "slides": config.DEFAULT_SLIDES, "theme": "classique",
                 "pdf": True, "agent": False, "role": None}


class AuthError(ValueError):
    """Message affichable tel quel à l'utilisateur."""


@dataclass
class User:
    id: int
    email: str
    name: str
    prefs: dict

    @property
    def folder(self) -> Path:
        return USERS_DIR / str(self.id)


@dataclass
class Project:
    id: int
    user_id: int
    title: str
    status: str          # outline (plan à valider), ready (présentation prête), failed
    stem: str            # fichiers du projet, sans extension
    source: str
    slides: int
    theme: str
    created: float
    updated: float


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            pw_hash BLOB NOT NULL, pw_salt BLOB NOT NULL,
            recovery_hash BLOB NOT NULL, recovery_salt BLOB NOT NULL,
            prefs TEXT NOT NULL DEFAULT '{}', failures INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL, status TEXT NOT NULL, stem TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '', slides INTEGER NOT NULL DEFAULT 0,
            theme TEXT NOT NULL DEFAULT 'classique',
            created REAL NOT NULL, updated REAL NOT NULL);
    """)
    return con


def _hash(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, **SCRYPT)


def _new_hash(secret: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(16)
    return _hash(secret, salt), salt


def _recovery_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sans 0/O, 1/I/L : se recopie sans erreur
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def _norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def _user(row) -> User:
    return User(row["id"], row["email"], row["name"], DEFAULT_PREFS | json.loads(row["prefs"]))


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Le mot de passe doit faire au moins {MIN_PASSWORD} caractères.")
    if password.isdigit() or password.isalpha():
        raise AuthError("Le mot de passe doit mélanger lettres et chiffres (ou symboles).")


# --- Comptes ----------------------------------------------------------------------

def _record_failure(con: sqlite3.Connection, row) -> None:
    """Compte un échec ; bloque le compte au-delà de MAX_FAILURES. Validé tout de suite :
    l'exception qui suit annulerait sinon la transaction (et donc le compteur)."""
    failures = row["failures"] + 1
    locked = time.time() + LOCK_SECONDS if failures >= MAX_FAILURES else 0
    con.execute("UPDATE users SET failures = ?, locked_until = ? WHERE id = ?",
                (0 if locked else failures, locked, row["id"]))
    con.commit()


def create_user(email: str, name: str, password: str) -> tuple[User, str]:
    """Crée le compte ; renvoie (utilisateur, code de secours à montrer une seule fois)."""
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise AuthError("Adresse e-mail invalide.")
    if not name.strip():
        raise AuthError("Indiquez votre nom.")
    check_password_rules(password)
    code = _recovery_code()
    pw_hash, pw_salt = _new_hash(password)
    rc_hash, rc_salt = _new_hash(_norm_code(code))
    with _db() as con:
        try:
            cur = con.execute(
                "INSERT INTO users (email, name, pw_hash, pw_salt, recovery_hash, recovery_salt,"
                " prefs, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (email, name.strip(), pw_hash, pw_salt, rc_hash, rc_salt, "{}", time.time()))
        except sqlite3.IntegrityError:
            raise AuthError("Un compte existe déjà avec cette adresse.") from None
        row = con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _user(row), code


def authenticate(email: str, password: str) -> User:
    email = email.strip().lower()
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            _hash(password, b"0" * 16)  # même durée qu'un vrai essai : ne révèle pas l'adresse
            raise AuthError("E-mail ou mot de passe incorrect.")
        if row["locked_until"] > time.time():
            wait = int(row["locked_until"] - time.time()) // 60 + 1
            raise AuthError(f"Trop d'essais : compte bloqué encore {wait} min.")
        if not hmac.compare_digest(_hash(password, row["pw_salt"]), row["pw_hash"]):
            _record_failure(con, row)
            raise AuthError("E-mail ou mot de passe incorrect.")
        con.execute("UPDATE users SET failures = 0, locked_until = 0 WHERE id = ?", (row["id"],))
        return _user(row)


def reset_password(email: str, code: str, new_password: str) -> str:
    """Mot de passe oublié : vérifie le code de secours, change le mot de passe.
    Renvoie un nouveau code de secours (l'ancien ne sert qu'une fois)."""
    check_password_rules(new_password)
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        valid = row is not None and row["locked_until"] <= time.time() and hmac.compare_digest(
            _hash(_norm_code(code), row["recovery_salt"]), row["recovery_hash"])
        if not valid:
            if row is not None:
                _record_failure(con, row)
            raise AuthError("E-mail ou code de secours incorrect.")
        new_code = _recovery_code()
        pw_hash, pw_salt = _new_hash(new_password)
        rc_hash, rc_salt = _new_hash(_norm_code(new_code))
        con.execute("UPDATE users SET pw_hash = ?, pw_salt = ?, recovery_hash = ?, "
                    "recovery_salt = ?, failures = 0, locked_until = 0 WHERE id = ?",
                    (pw_hash, pw_salt, rc_hash, rc_salt, row["id"]))
    return new_code


def change_password(user: User, current: str, new_password: str) -> None:
    authenticate(user.email, current)
    check_password_rules(new_password)
    pw_hash, pw_salt = _new_hash(new_password)
    with _db() as con:
        con.execute("UPDATE users SET pw_hash = ?, pw_salt = ? WHERE id = ?",
                    (pw_hash, pw_salt, user.id))


def get_user(user_id: int) -> User | None:
    with _db() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user(row) if row else None


def update_profile(user: User, name: str, prefs: dict) -> User:
    if not name.strip():
        raise AuthError("Le nom ne peut pas être vide.")
    merged = user.prefs | prefs
    with _db() as con:
        con.execute("UPDATE users SET name = ?, prefs = ? WHERE id = ?",
                    (name.strip(), json.dumps(merged), user.id))
    return User(user.id, user.email, name.strip(), merged)


# --- Projets ------------------------------------------------------------------------

def _project(row) -> Project:
    return Project(**{k: row[k] for k in row.keys()})


def create_project(user: User, title: str, source: str, slides: int, theme: str) -> Project:
    now = time.time()
    user.folder.mkdir(parents=True, exist_ok=True)
    with _db() as con:
        cur = con.execute(
            "INSERT INTO projects (user_id, title, status, stem, source, slides, theme, created,"
            " updated) VALUES (?, ?, 'outline', '', ?, ?, ?, ?, ?)",
            (user.id, title.strip() or "Présentation", source, slides, theme, now, now))
        stem = str(user.folder / f"projet_{cur.lastrowid}")
        con.execute("UPDATE projects SET stem = ? WHERE id = ?", (stem, cur.lastrowid))
        row = con.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _project(row)


def update_project(project: Project, **fields) -> Project:
    allowed = {"title", "status", "slides", "theme", "source"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    fields["updated"] = time.time()
    with _db() as con:
        con.execute(f"UPDATE projects SET {', '.join(f'{k} = ?' for k in fields)} "
                    "WHERE id = ? AND user_id = ?", (*fields.values(), project.id, project.user_id))
        row = con.execute("SELECT * FROM projects WHERE id = ?", (project.id,)).fetchone()
    return _project(row)


def list_projects(user: User, search: str = "") -> list[Project]:
    with _db() as con:
        rows = con.execute("SELECT * FROM projects WHERE user_id = ? AND title LIKE ? "
                           "ORDER BY updated DESC", (user.id, f"%{search.strip()}%")).fetchall()
    return [_project(r) for r in rows]


def get_project(user: User, project_id: int) -> Project | None:
    """Projet de cet utilisateur uniquement (jamais celui d'un autre compte)."""
    with _db() as con:
        row = con.execute("SELECT * FROM projects WHERE id = ? AND user_id = ?",
                          (project_id, user.id)).fetchone()
    return _project(row) if row else None


def delete_project(user: User, project: Project) -> None:
    with _db() as con:
        con.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project.id, user.id))
    stem = Path(project.stem)
    for f in stem.parent.glob(stem.name + ".*"):
        f.unlink(missing_ok=True)
