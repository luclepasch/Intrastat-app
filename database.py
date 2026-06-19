"""
database.py — Couche d'accès aux données (utilisateurs).

Supporte deux backends, choisis via configuration :
  - SQLite (par défaut)   : aucun service externe requis.
  - PostgreSQL (optionnel) : définir DB_BACKEND=postgres + DATABASE_URL.

Configuration (variables d'environnement OU st.secrets) :
  DB_BACKEND     : "sqlite" (défaut) ou "postgres"
  SQLITE_PATH    : chemin du fichier SQLite (défaut "users.db")
  DATABASE_URL   : URL de connexion PostgreSQL (ex: postgresql://user:pwd@host:5432/db)

⚠️ Sur Streamlit Community Cloud, le système de fichiers est éphémère : la base
SQLite est réinitialisée à chaque redémarrage. Pour une persistance durable,
utilisez PostgreSQL (Neon, Supabase, Railway…).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

try:
    import streamlit as st
except Exception:  # streamlit absent (tests unitaires)
    st = None


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def get_config(key: str, default: Optional[str] = None) -> Optional[str]:
    """Lit une valeur de configuration dans st.secrets puis l'environnement."""
    if st is not None:
        try:
            if key in st.secrets:
                return str(st.secrets[key])
        except Exception:
            pass
    return os.environ.get(key, default)


BACKEND = (get_config("DB_BACKEND", "sqlite") or "sqlite").lower()
SQLITE_PATH = get_config("SQLITE_PATH", "users.db")
DATABASE_URL = get_config("DATABASE_URL")

_IS_PG = BACKEND in ("postgres", "postgresql", "pg")


# --------------------------------------------------------------------------- #
# Connexion bas niveau
# --------------------------------------------------------------------------- #
def _connect():
    """Ouvre une connexion vers le backend configuré."""
    if _IS_PG:
        import psycopg2  # import paresseux : requis seulement en mode PostgreSQL

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL est requis lorsque DB_BACKEND=postgres.")
        return psycopg2.connect(DATABASE_URL)
    import sqlite3

    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    return conn


def _adapt(query: str) -> str:
    """Adapte les placeholders '?' vers '%s' pour PostgreSQL."""
    return query.replace("?", "%s") if _IS_PG else query


def _run(query: str, params: tuple = (), fetch: Optional[str] = None) -> Any:
    """Exécute une requête. fetch ∈ {None, 'one', 'all', 'id'}."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_adapt(query), params)

        if fetch == "one":
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.commit()
            return dict(zip(cols, row)) if row else None

        if fetch == "all":
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            conn.commit()
            return [dict(zip(cols, r)) for r in rows]

        conn.commit()
        if fetch == "id":
            # Récupère l'identifiant du dernier enregistrement inséré
            return getattr(cur, "lastrowid", None)
        return None
    finally:
        conn.close()


def _now() -> str:
    """Horodatage ISO 8601 (UTC), stocké en TEXT pour rester compatible SQLite/PG."""
    return datetime.utcnow().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Création des tables
# --------------------------------------------------------------------------- #
def init_db() -> None:
    """Crée la table `users` si elle n'existe pas."""
    if _IS_PG:
        id_col = "id BIGSERIAL PRIMARY KEY"
    else:
        id_col = "id INTEGER PRIMARY KEY AUTOINCREMENT"

    _run(
        f"""
        CREATE TABLE IF NOT EXISTS users (
            {id_col},
            email          TEXT UNIQUE NOT NULL,
            password_hash  TEXT NOT NULL,
            full_name      TEXT,
            role           TEXT NOT NULL DEFAULT 'USER',
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT,
            updated_at     TEXT,
            last_login_at  TEXT,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until   TEXT
        )
        """
    )


# --------------------------------------------------------------------------- #
# CRUD utilisateurs
# --------------------------------------------------------------------------- #
def create_user(email: str, password_hash: str, full_name: str = "",
                role: str = "USER", is_active: bool = True) -> int:
    """Crée un utilisateur et renvoie son id."""
    now = _now()
    _run(
        """INSERT INTO users (email, password_hash, full_name, role, is_active,
                              created_at, updated_at, failed_attempts)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (email.lower().strip(), password_hash, full_name.strip(), role,
         1 if is_active else 0, now, now),
    )
    user = get_user_by_email(email)
    return user["id"] if user else -1


def get_user_by_email(email: str) -> Optional[dict]:
    return _run("SELECT * FROM users WHERE email = ?",
                (email.lower().strip(),), fetch="one")


def get_user_by_id(user_id: int) -> Optional[dict]:
    return _run("SELECT * FROM users WHERE id = ?", (user_id,), fetch="one")


def list_users(search: str = "") -> list[dict]:
    """Liste les utilisateurs, filtrés par email ou nom si `search` est fourni."""
    if search:
        like = f"%{search.lower().strip()}%"
        return _run(
            """SELECT * FROM users
               WHERE LOWER(email) LIKE ? OR LOWER(COALESCE(full_name,'')) LIKE ?
               ORDER BY id""",
            (like, like), fetch="all",
        )
    return _run("SELECT * FROM users ORDER BY id", fetch="all")


def count_users() -> int:
    row = _run("SELECT COUNT(*) AS n FROM users", fetch="one")
    return int(row["n"]) if row else 0


def update_role(user_id: int, role: str) -> None:
    _run("UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
         (role, _now(), user_id))


def set_active(user_id: int, active: bool) -> None:
    _run("UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
         (1 if active else 0, _now(), user_id))


def update_password(user_id: int, password_hash: str) -> None:
    _run("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
         (password_hash, _now(), user_id))


def update_full_name(user_id: int, full_name: str) -> None:
    _run("UPDATE users SET full_name = ?, updated_at = ? WHERE id = ?",
         (full_name.strip(), _now(), user_id))


def update_last_login(user_id: int) -> None:
    _run("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), user_id))


def delete_user(user_id: int) -> None:
    _run("DELETE FROM users WHERE id = ?", (user_id,))


# --------------------------------------------------------------------------- #
# Protection anti brute-force
# --------------------------------------------------------------------------- #
def increment_failed(user_id: int) -> None:
    _run("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id = ?",
         (user_id,))


def reset_failed(user_id: int) -> None:
    _run("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
         (user_id,))


def set_lock(user_id: int, locked_until_iso: Optional[str]) -> None:
    _run("UPDATE users SET locked_until = ? WHERE id = ?",
         (locked_until_iso, user_id))
