"""
auth.py — Authentification et gestion de session.

Fournit :
  - hash_password / verify_password  (bcrypt)
  - register_user                    (inscription)
  - login / logout                   (connexion / déconnexion)
  - get_current_user / is_authenticated
  - require_role(role)               (décorateur de protection des pages)
  - render_auth_page                 (formulaires login + inscription)
  - ensure_seed_admin                (création du 1er admin)

Sessions stockées dans st.session_state :
  is_authenticated, user_id, email, role, full_name
"""

from __future__ import annotations

import functools
import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import streamlit as st

import database as db

# --------------------------------------------------------------------------- #
# Paramètres de sécurité
# --------------------------------------------------------------------------- #
ROLES = ("ADMIN", "USER")
MIN_PASSWORD_LEN = 8
MAX_FAILED_ATTEMPTS = 5           # tentatives avant verrouillage
LOCK_MINUTES = 15                 # durée du verrouillage
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _flag(key: str, default: bool) -> bool:
    """Lit un drapeau booléen depuis la configuration (secrets/env)."""
    val = db.get_config(key)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on", "oui")


def registration_enabled() -> bool:
    """Inscription activable via la variable ENABLE_REGISTRATION (défaut : True)."""
    return _flag("ENABLE_REGISTRATION", True)


# --------------------------------------------------------------------------- #
# Hachage des mots de passe (bcrypt)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Renvoie le hash bcrypt du mot de passe (jamais stocké en clair)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Vérifie un mot de passe face à son hash bcrypt."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Validation des entrées
# --------------------------------------------------------------------------- #
def _valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) >= MIN_PASSWORD_LEN


# --------------------------------------------------------------------------- #
# Inscription
# --------------------------------------------------------------------------- #
def register_user(email: str, password: str, full_name: str = "",
                  role: str = "USER", plan: str = "FREE",
                  active: bool = True) -> tuple[bool, str]:
    """Crée un nouvel utilisateur. Renvoie (succès, message).

    `active=False` crée un compte EN ATTENTE de validation par un administrateur,
    et notifie l'admin par e-mail (si SMTP configuré).
    """
    import quotas  # plans disponibles

    email = (email or "").strip().lower()
    if not _valid_email(email):
        return False, "Adresse e-mail invalide."
    if not _valid_password(password):
        return False, f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LEN} caractères."
    if role not in ROLES:
        role = "USER"
    if plan not in quotas.PLANS:
        plan = "FREE"
    if db.get_user_by_email(email):
        return False, "Un compte existe déjà avec cette adresse e-mail."

    db.create_user(email, hash_password(password), full_name, role,
                   is_active=active, plan=plan)

    if not active:
        try:
            import mailer
            mailer.notify_admin_new_registration(email, full_name, plan)
        except Exception:
            pass  # l'absence d'e-mail ne bloque pas l'inscription
        return True, "Inscription enregistrée."

    return True, "Compte créé avec succès."


# --------------------------------------------------------------------------- #
# Connexion / Déconnexion
# --------------------------------------------------------------------------- #
def _is_locked(user: dict) -> bool:
    """Vrai si le compte est temporairement verrouillé (anti brute-force)."""
    locked_until = user.get("locked_until")
    if not locked_until:
        return False
    try:
        return datetime.utcnow() < datetime.fromisoformat(locked_until)
    except ValueError:
        return False


def login(email: str, password: str) -> tuple[bool, str]:
    """Authentifie l'utilisateur et initialise la session. Renvoie (succès, message)."""
    email = (email or "").strip().lower()
    user = db.get_user_by_email(email)

    # Réponse volontairement générique pour ne pas révéler l'existence du compte
    generic_err = "E-mail ou mot de passe incorrect."

    if not user:
        return False, generic_err
    if not int(user.get("is_active", 1)):
        return False, ("Compte en attente de validation par un administrateur, "
                       "ou désactivé. Réessayez plus tard.")
    if _is_locked(user):
        return False, (f"Compte temporairement verrouillé après plusieurs échecs. "
                       f"Réessayez dans quelques minutes.")

    if not verify_password(password, user["password_hash"]):
        # Compteur d'échecs + verrouillage éventuel
        db.increment_failed(user["id"])
        attempts = int(user.get("failed_attempts", 0)) + 1
        if attempts >= MAX_FAILED_ATTEMPTS:
            until = (datetime.utcnow() + timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
            db.set_lock(user["id"], until)
            return False, (f"Trop de tentatives. Compte verrouillé pendant {LOCK_MINUTES} minutes.")
        return False, generic_err

    # Succès : réinitialise les compteurs, met à jour last_login, ouvre la session
    db.reset_failed(user["id"])
    db.update_last_login(user["id"])
    st.session_state["is_authenticated"] = True
    st.session_state["user_id"] = user["id"]
    st.session_state["email"] = user["email"]
    st.session_state["role"] = user["role"]
    st.session_state["full_name"] = user.get("full_name") or ""
    return True, "Connexion réussie."


def logout() -> None:
    """Ferme la session courante."""
    for key in ("is_authenticated", "user_id", "email", "role", "full_name"):
        st.session_state.pop(key, None)


def change_password(user_id: int, current_password: str,
                    new_password: str) -> tuple[bool, str]:
    """Change le mot de passe de l'utilisateur après vérification de l'actuel."""
    user = db.get_user_by_id(user_id)
    if not user:
        return False, "Utilisateur introuvable."
    if not verify_password(current_password, user["password_hash"]):
        return False, "Le mot de passe actuel est incorrect."
    if not _valid_password(new_password):
        return False, f"Le nouveau mot de passe doit contenir au moins {MIN_PASSWORD_LEN} caractères."
    if verify_password(new_password, user["password_hash"]):
        return False, "Le nouveau mot de passe doit être différent de l'actuel."
    db.update_password(user_id, hash_password(new_password))
    return True, "Mot de passe modifié avec succès."


def update_profile_name(user_id: int, full_name: str) -> tuple[bool, str]:
    """Met à jour le nom complet de l'utilisateur et la session."""
    db.update_full_name(user_id, full_name)
    if st.session_state.get("user_id") == user_id:
        st.session_state["full_name"] = full_name.strip()
    return True, "Profil mis à jour."


# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #
def is_authenticated() -> bool:
    return bool(st.session_state.get("is_authenticated"))


def get_current_user() -> Optional[dict]:
    """Renvoie l'utilisateur courant (depuis la session) ou None."""
    if not is_authenticated():
        return None
    return {
        "id": st.session_state.get("user_id"),
        "email": st.session_state.get("email"),
        "role": st.session_state.get("role"),
        "full_name": st.session_state.get("full_name"),
    }


def has_role(role: str) -> bool:
    """Vrai si l'utilisateur courant possède le rôle requis (ADMIN couvre tout)."""
    user = get_current_user()
    if not user:
        return False
    if user["role"] == "ADMIN":
        return True
    return user["role"] == role


def require_role(role: str):
    """Décorateur protégeant une page/fonction selon le rôle requis."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_authenticated():
                st.warning("🔒 Veuillez vous connecter pour accéder à cette page.")
                st.stop()
            if not has_role(role):
                st.error("⛔ Accès refusé : autorisation insuffisante.")
                st.stop()
            return func(*args, **kwargs)
        return wrapper
    return decorator


# --------------------------------------------------------------------------- #
# Amorçage du premier administrateur
# --------------------------------------------------------------------------- #
def ensure_seed_admin() -> Optional[str]:
    """
    Crée un compte ADMIN initial si la base est vide.

    Identifiants lus depuis la configuration (ADMIN_EMAIL / ADMIN_PASSWORD).
    À défaut, un compte par défaut est créé et DOIT être changé immédiatement.
    Renvoie un message d'avertissement si un mot de passe par défaut a été utilisé.
    """
    if db.count_users() > 0:
        return None

    email = (db.get_config("ADMIN_EMAIL") or "admin@plantdoctor.local").strip().lower()
    password = db.get_config("ADMIN_PASSWORD")
    warning = None
    if not password:
        password = "ChangeMe123!"
        warning = (f"⚠️ Un administrateur par défaut a été créé : **{email}** / "
                   f"`{password}`. Changez ce mot de passe immédiatement, ou définissez "
                   f"ADMIN_EMAIL/ADMIN_PASSWORD dans la configuration.")

    db.create_user(email, hash_password(password), "Administrateur", "ADMIN", True)
    return warning


# --------------------------------------------------------------------------- #
# Pages d'authentification (UI Streamlit)
# --------------------------------------------------------------------------- #
def render_auth_page() -> None:
    """Affiche l'écran d'accueil avec deux onglets : Connexion et Inscription."""
    import quotas

    st.markdown("## 🌿 Bienvenue sur Plant Doctor")

    # Deux onglets toujours visibles côte à côte
    tab_login, tab_register = st.tabs(["🔑 Connexion", "📝 Inscription"])

    # --- Connexion ---
    with tab_login:
        with st.form("form_login"):
            email = st.text_input("E-mail", key="login_email")
            password = st.text_input("Mot de passe", type="password", key="login_pw")
            submit = st.form_submit_button("Se connecter")
        if submit:
            ok, msg = login(email, password)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    # --- Inscription ---
    with tab_register:
        if not registration_enabled():
            st.info("ℹ️ Les inscriptions sont actuellement fermées. "
                    "Contactez un administrateur pour obtenir un compte.")
        else:
            st.caption("Créez votre compte. Il sera activé après validation par un administrateur.")
            with st.form("form_register"):
                full_name = st.text_input("Nom complet", key="reg_name")
                email_r = st.text_input("E-mail", key="reg_email")
                pw1 = st.text_input("Mot de passe", type="password", key="reg_pw1")
                pw2 = st.text_input("Confirmer le mot de passe", type="password", key="reg_pw2")
                plan = st.selectbox("Formule souhaitée", quotas.PLANS, key="reg_plan")
                submit_r = st.form_submit_button("Créer mon compte")
            if submit_r:
                if pw1 != pw2:
                    st.error("Les deux mots de passe ne correspondent pas.")
                else:
                    ok, msg = register_user(email_r, pw1, full_name, role="USER",
                                            plan=plan, active=False)
                    if ok:
                        st.success(
                            "✅ Inscription enregistrée ! Votre compte sera actif "
                            "après validation par un administrateur."
                        )
                    else:
                        st.error(msg)
