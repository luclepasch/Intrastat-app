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
import threading
from datetime import datetime, timedelta
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
    """Ouvre une connexion vers le backend configuré (en mode autocommit)."""
    if _IS_PG:
        import psycopg2  # import paresseux : requis seulement en mode PostgreSQL

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL est requis lorsque DB_BACKEND=postgres.")
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True  # évite les transactions "idle" qui ralentissent
        return conn
    import sqlite3

    conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    conn.isolation_level = None  # autocommit
    return conn


# Connexion persistante réutilisée entre les requêtes (évite un handshake TLS à
# chaque appel — c'est LE gain de performance principal avec un pooler distant).
_conn = None
_lock = threading.RLock()


def _get_connection():
    """Renvoie la connexion partagée, en la (ré)ouvrant si nécessaire."""
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        return _conn


def _reset_connection() -> None:
    """Ferme/oublie la connexion courante (forcera une reconnexion)."""
    global _conn
    with _lock:
        try:
            if _conn is not None:
                _conn.close()
        except Exception:
            pass
        _conn = None


def _adapt(query: str) -> str:
    """Adapte les placeholders '?' vers '%s' pour PostgreSQL."""
    return query.replace("?", "%s") if _IS_PG else query


def _is_connection_error(exc: Exception) -> bool:
    """Vrai si l'erreur indique une connexion perdue (à reconnecter)."""
    return type(exc).__name__ in ("OperationalError", "InterfaceError")


def _run(query: str, params: tuple = (), fetch: Optional[str] = None) -> Any:
    """Exécute une requête sur la connexion partagée. fetch ∈ {None,'one','all','id'}.

    Réessaie une fois en cas de connexion perdue (Supabase ferme les connexions
    inactives) ; les autres erreurs SQL sont propagées immédiatement.
    """
    last_err = None
    for attempt in range(2):
        try:
            with _lock:
                conn = _get_connection()
                cur = conn.cursor()
                cur.execute(_adapt(query), params)
                if fetch == "one":
                    row = cur.fetchone()
                    cols = [d[0] for d in cur.description] if cur.description else []
                    cur.close()
                    return dict(zip(cols, row)) if row else None
                if fetch == "all":
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description] if cur.description else []
                    cur.close()
                    return [dict(zip(cols, r)) for r in rows]
                last_id = getattr(cur, "lastrowid", None)
                cur.close()
                return last_id if fetch == "id" else None
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if _is_connection_error(exc) and attempt == 0:
                _reset_connection()  # reconnexion puis nouvel essai
                continue
            raise
    raise last_err


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
            locked_until   TEXT,
            plan           TEXT DEFAULT 'FREE',
            title          TEXT,
            first_name     TEXT,
            last_name      TEXT
        )
        """
    )

    # Colonnes ajoutées de façon idempotente pour les bases existantes
    existing = _existing_columns("users")
    migrations = [
        ("quota_day", "quota_day INTEGER"),
        ("quota_week", "quota_week INTEGER"),
        ("quota_month", "quota_month INTEGER"),
        ("quota_year", "quota_year INTEGER"),
        ("plan", "plan TEXT DEFAULT 'FREE'"),
        ("title", "title TEXT"),
        ("first_name", "first_name TEXT"),
        ("last_name", "last_name TEXT"),
    ]
    for col_name, coldef in migrations:
        if col_name not in existing:
            _safe_add_column("users", col_name, coldef)

    # Journal d'utilisation : une ligne par analyse effectuée
    usage_id = "id BIGSERIAL PRIMARY KEY" if _IS_PG else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    _run(
        f"""
        CREATE TABLE IF NOT EXISTS usage_log (
            {usage_id},
            user_id    INTEGER NOT NULL,
            created_at TEXT
        )
        """
    )

    # Historique persistant des analyses (résultat + miniatures des photos)
    an_id = "id BIGSERIAL PRIMARY KEY" if _IS_PG else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    _run(
        f"""
        CREATE TABLE IF NOT EXISTS analyses (
            {an_id},
            user_id    INTEGER NOT NULL,
            created_at TEXT,
            plante     TEXT,
            score      INTEGER,
            diagnostic TEXT,
            thumbnails TEXT
        )
        """
    )


def _existing_columns(table: str) -> set:
    """Renvoie l'ensemble des colonnes existantes d'une table (SQLite/PG)."""
    try:
        if _IS_PG:
            rows = _run(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
                (table,), fetch="all",
            )
            return {r["column_name"] for r in rows}
        rows = _run(f"PRAGMA table_info({table})", fetch="all")
        return {r["name"] for r in rows}
    except Exception:
        return set()


def _safe_add_column(table: str, col_name: str, coldef: str) -> None:
    """Ajoute une colonne si elle n'existe pas déjà (compatible SQLite/PG)."""
    try:
        if col_name in _existing_columns(table):
            return
        _run(f"ALTER TABLE {table} ADD COLUMN {coldef}")
    except Exception:
        pass  # la colonne existe déjà ou course concurrente


# --------------------------------------------------------------------------- #
# CRUD utilisateurs
# --------------------------------------------------------------------------- #
def _compose_full_name(title: str, first_name: str, last_name: str, fallback: str = "") -> str:
    parts = [p.strip() for p in (title, first_name, last_name) if p and p.strip()]
    return " ".join(parts) if parts else fallback.strip()


def create_user(email: str, password_hash: str, full_name: str = "",
                role: str = "USER", is_active: bool = True, plan: str = "FREE",
                title: str = "", first_name: str = "", last_name: str = "") -> int:
    """Crée un utilisateur et renvoie son id."""
    full_name = _compose_full_name(title, first_name, last_name, full_name)
    now = _now()
    _run(
        """INSERT INTO users (email, password_hash, full_name, role, is_active, plan,
                              title, first_name, last_name,
                              created_at, updated_at, failed_attempts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (email.lower().strip(), password_hash, full_name, role,
         1 if is_active else 0, plan, title.strip(), first_name.strip(),
         last_name.strip(), now, now),
    )
    user = get_user_by_email(email)
    return user["id"] if user else -1


def update_user_identity(user_id: int, title: str, first_name: str, last_name: str) -> str:
    """Met à jour titre/prénom/nom (+ full_name) ; renvoie le nom complet."""
    full_name = _compose_full_name(title, first_name, last_name)
    _run(
        """UPDATE users SET title = ?, first_name = ?, last_name = ?,
               full_name = ?, updated_at = ? WHERE id = ?""",
        (title.strip(), first_name.strip(), last_name.strip(), full_name, _now(), user_id),
    )
    return full_name


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


def set_user_plan(user_id: int, plan: str) -> None:
    _run("UPDATE users SET plan = ?, updated_at = ? WHERE id = ?",
         (plan, _now(), user_id))


def list_pending_users() -> list[dict]:
    """Comptes en attente de validation (inactifs)."""
    return _run("SELECT * FROM users WHERE is_active = 0 ORDER BY id", fetch="all")


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


# --------------------------------------------------------------------------- #
# Quotas d'analyses
# --------------------------------------------------------------------------- #
def log_usage(user_id: int) -> None:
    """Enregistre une analyse pour le décompte des quotas."""
    _run("INSERT INTO usage_log (user_id, created_at) VALUES (?, ?)",
         (user_id, _now()))


def count_usage_since(user_id: int, since_iso: str) -> int:
    """Nombre d'analyses d'un utilisateur depuis l'horodatage `since_iso`."""
    row = _run(
        "SELECT COUNT(*) AS n FROM usage_log WHERE user_id = ? AND created_at >= ?",
        (user_id, since_iso), fetch="one",
    )
    return int(row["n"]) if row else 0


def usage_counts_multi(user_id: int, day_iso: str, week_iso: str,
                       month_iso: str, year_iso: str) -> dict:
    """Compte les analyses sur les 4 périodes en UNE seule requête."""
    row = _run(
        """SELECT
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS d,
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS w,
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS m,
              SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS y
           FROM usage_log WHERE user_id = ?""",
        (day_iso, week_iso, month_iso, year_iso, user_id), fetch="one",
    )
    if not row:
        return {"day": 0, "week": 0, "month": 0, "year": 0}
    return {
        "day": int(row["d"] or 0), "week": int(row["w"] or 0),
        "month": int(row["m"] or 0), "year": int(row["y"] or 0),
    }


def set_user_quota(user_id: int, day, week, month, year) -> None:
    """Définit les quotas (None = pas de limite spécifique) d'un utilisateur."""
    _run(
        """UPDATE users
           SET quota_day = ?, quota_week = ?, quota_month = ?, quota_year = ?,
               updated_at = ?
           WHERE id = ?""",
        (day, week, month, year, _now(), user_id),
    )


# --------------------------------------------------------------------------- #
# Statistiques (tableau de bord admin)
# --------------------------------------------------------------------------- #
def users_summary() -> dict:
    """Synthèse des comptes : total, actifs, inactifs, admins, users, verrouillés."""
    row = _run(
        """SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS actifs,
              SUM(CASE WHEN role = 'ADMIN' THEN 1 ELSE 0 END) AS admins,
              SUM(CASE WHEN locked_until IS NOT NULL THEN 1 ELSE 0 END) AS verrouilles
           FROM users""",
        fetch="one",
    )
    total = int(row["total"] or 0)
    actifs = int(row["actifs"] or 0)
    admins = int(row["admins"] or 0)
    return {
        "total": total, "actifs": actifs, "inactifs": total - actifs,
        "admins": admins, "users": total - admins,
        "verrouilles": int(row["verrouilles"] or 0),
    }


def usage_total() -> int:
    row = _run("SELECT COUNT(*) AS n FROM usage_log", fetch="one")
    return int(row["n"] or 0) if row else 0


def usage_global_since(since_iso: str) -> int:
    row = _run("SELECT COUNT(*) AS n FROM usage_log WHERE created_at >= ?",
               (since_iso,), fetch="one")
    return int(row["n"] or 0) if row else 0


def usage_by_day(since_iso: str) -> list[dict]:
    """Analyses par jour depuis `since_iso` (jour au format AAAA-MM-JJ)."""
    return _run(
        """SELECT substr(created_at, 1, 10) AS jour, COUNT(*) AS n
           FROM usage_log WHERE created_at >= ?
           GROUP BY substr(created_at, 1, 10) ORDER BY jour""",
        (since_iso,), fetch="all",
    )


def top_users_by_usage(limit: int = 10) -> list[dict]:
    """Utilisateurs classés par nombre total d'analyses."""
    return _run(
        """SELECT u.email AS email, u.role AS role, COUNT(l.id) AS n
           FROM users u LEFT JOIN usage_log l ON l.user_id = u.id
           GROUP BY u.id, u.email, u.role
           ORDER BY n DESC, u.email
           LIMIT ?""",
        (limit,), fetch="all",
    )


def recent_usage(limit: int = 15) -> list[dict]:
    """Dernières analyses (email + horodatage)."""
    return _run(
        """SELECT u.email AS email, l.created_at AS created_at
           FROM usage_log l JOIN users u ON u.id = l.user_id
           ORDER BY l.created_at DESC LIMIT ?""",
        (limit,), fetch="all",
    )


# --------------------------------------------------------------------------- #
# Historique persistant des analyses
# --------------------------------------------------------------------------- #
def save_analysis(user_id: int, plante: str, score: int,
                  diagnostic_json: str, thumbnails_json: str) -> None:
    """Enregistre une analyse (diagnostic + miniatures) pour un utilisateur."""
    _run(
        """INSERT INTO analyses (user_id, created_at, plante, score, diagnostic, thumbnails)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, _now(), plante, int(score or 0), diagnostic_json, thumbnails_json),
    )


def list_analyses(user_id: int, limit: int = 50) -> list[dict]:
    """Liste des analyses d'un utilisateur (avec les miniatures pour les vignettes)."""
    return _run(
        """SELECT id, created_at, plante, score, thumbnails FROM analyses
           WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
        (user_id, limit), fetch="all",
    )


def get_analysis(analysis_id: int, user_id: int) -> Optional[dict]:
    """Récupère une analyse complète (diagnostic + miniatures) de l'utilisateur."""
    return _run(
        "SELECT * FROM analyses WHERE id = ? AND user_id = ?",
        (analysis_id, user_id), fetch="one",
    )


def delete_analysis(analysis_id: int, user_id: int) -> None:
    _run("DELETE FROM analyses WHERE id = ? AND user_id = ?", (analysis_id, user_id))


def delete_all_analyses(user_id: int) -> None:
    _run("DELETE FROM analyses WHERE user_id = ?", (user_id,))


def count_stored_analyses() -> int:
    row = _run("SELECT COUNT(*) AS n FROM analyses", fetch="one")
    return int(row["n"] or 0) if row else 0


def count_analyses_before(before_iso: str) -> int:
    row = _run("SELECT COUNT(*) AS n FROM analyses WHERE created_at < ?",
               (before_iso,), fetch="one")
    return int(row["n"] or 0) if row else 0


def delete_analyses_before(before_iso: str) -> None:
    """Supprime toutes les analyses antérieures à `before_iso` (purge globale)."""
    _run("DELETE FROM analyses WHERE created_at < ?", (before_iso,))


def retention_cutoff_iso() -> Optional[str]:
    """Date limite de rétention (ISO) selon ANALYSIS_RETENTION_MONTHS, ou None."""
    val = get_config("ANALYSIS_RETENTION_MONTHS")
    try:
        months = int(val) if val not in (None, "") else 0
    except ValueError:
        months = 0
    if months <= 0:
        return None
    return (datetime.utcnow() - timedelta(days=months * 30)).isoformat(timespec="seconds")
