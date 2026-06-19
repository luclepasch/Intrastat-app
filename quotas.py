"""
quotas.py — Gestion des quotas d'analyses par utilisateur.

Limites possibles : par jour, par semaine, par mois, par an.

Priorité des limites pour chaque période :
  1. Quota propre à l'utilisateur (colonnes quota_day/week/month/year)
  2. Sinon, valeur par défaut globale (config QUOTA_DAY/WEEK/MONTH/YEAR)
  3. Sinon, illimité.

Une valeur 0 ou vide = pas de limite pour cette période.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import database as db

PERIODES = ("day", "week", "month", "year")
LABELS = {"day": "jour", "week": "semaine", "month": "mois", "year": "an"}

# Trois plans d'abonnement avec des quotas d'analyses différents (0 = illimité).
PLANS = ("FREE", "STANDARD", "PREMIUM")
PLAN_DEFAULTS = {
    "FREE":     {"day": 3,  "week": 10,  "month": 30,  "year": 200},
    "STANDARD": {"day": 20, "week": 120, "month": 400, "year": 3000},
    "PREMIUM":  {"day": 0,  "week": 0,   "month": 0,   "year": 0},  # illimité
}


def plan_limits(plan: str) -> dict:
    """Quotas d'un plan (surchargés par PLAN_<PLAN>_<PERIODE> si défini)."""
    plan = plan if plan in PLAN_DEFAULTS else "FREE"
    base = PLAN_DEFAULTS[plan]
    out = {}
    for p in PERIODES:
        v = db.get_config(f"PLAN_{plan}_{p.upper()}")
        try:
            out[p] = int(v) if v not in (None, "") else base[p]
        except ValueError:
            out[p] = base[p]
    return out


def _cfg_int(key: str):
    """Lit un entier de configuration ; None si absent/vide/≤0."""
    val = db.get_config(key)
    if val is None or str(val).strip() == "":
        return None
    try:
        n = int(str(val).strip())
        return n if n > 0 else None
    except ValueError:
        return None


def _config_defaults() -> dict:
    return {
        "day": _cfg_int("QUOTA_DAY"),
        "week": _cfg_int("QUOTA_WEEK"),
        "month": _cfg_int("QUOTA_MONTH"),
        "year": _cfg_int("QUOTA_YEAR"),
    }


def effective_limits(user: dict) -> dict:
    """Limites effectives par période (int) ou None (illimité).

    Priorité : quota explicite de l'utilisateur > quota du plan > défaut global.
    """
    gdefaults = _config_defaults()
    plimits = plan_limits(user.get("plan") or "FREE")
    out = {}
    for p in PERIODES:
        col = user.get(f"quota_{p}")
        if col not in (None, ""):
            base = int(col)
        else:
            pv = plimits.get(p)
            base = pv if pv is not None else gdefaults[p]
        out[p] = base if (base and base > 0) else None
    return out


def _period_start(now: datetime, period: str) -> str:
    """Horodatage ISO du début de la période (UTC)."""
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start = d
    elif period == "week":
        start = d - timedelta(days=now.weekday())  # lundi
    elif period == "month":
        start = d.replace(day=1)
    else:  # year
        start = d.replace(month=1, day=1)
    return start.isoformat(timespec="seconds")


def usage_counts(user_id: int, now: datetime = None) -> dict:
    """Nombre d'analyses déjà effectuées sur chaque période (1 seule requête)."""
    now = now or datetime.utcnow()
    return db.usage_counts_multi(
        user_id,
        _period_start(now, "day"), _period_start(now, "week"),
        _period_start(now, "month"), _period_start(now, "year"),
    )


def check_quota(user_id: int) -> tuple[bool, str, dict]:
    """
    Vérifie si l'utilisateur peut lancer une analyse.
    Renvoie (autorisé, message, infos {limits, counts}).
    """
    user = db.get_user_by_id(user_id)
    if not user:
        return True, "", {}
    limits = effective_limits(user)
    counts = usage_counts(user_id)
    for p in PERIODES:
        lim = limits[p]
        if lim is not None and counts[p] >= lim:
            return (False,
                    f"Quota atteint : {lim} analyse(s) par {LABELS[p]}. Réessayez plus tard.",
                    {"limits": limits, "counts": counts})
    return True, "", {"limits": limits, "counts": counts}


def record_analysis(user_id: int) -> None:
    """Enregistre une analyse consommée."""
    db.log_usage(user_id)


def quota_caption(user_id: int) -> str:
    """Phrase résumant les analyses restantes (périodes limitées seulement)."""
    user = db.get_user_by_id(user_id)
    if not user:
        return ""
    limits = effective_limits(user)
    counts = usage_counts(user_id)
    parts = []
    for p in PERIODES:
        lim = limits[p]
        if lim is not None:
            restant = max(0, lim - counts[p])
            parts.append(f"{LABELS[p]} : {restant}/{lim}")
    if not parts:
        return "📊 Analyses : illimitées"
    return "📊 Analyses restantes — " + "  ·  ".join(parts)
