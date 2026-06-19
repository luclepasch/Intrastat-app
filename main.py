"""
main.py — Point d'entrée avec authentification.

Lancement :
    streamlit run main.py

Ce fichier protège l'application "Plant Doctor" (plante_sante_app.py) derrière
une couche d'authentification :
  - redirection automatique vers la page de connexion si non connecté ;
  - barre latérale avec nom d'utilisateur, rôle et bouton de déconnexion ;
  - navigation vers l'administration pour les comptes ADMIN ;
  - l'application métier reste inchangée et exécutable seule.

Configuration utile (st.secrets ou variables d'environnement) :
  ANTHROPIC_API_KEY    : clé de l'API Claude (pour Plant Doctor)
  DB_BACKEND           : "sqlite" (défaut) ou "postgres"
  DATABASE_URL         : URL PostgreSQL si DB_BACKEND=postgres
  ADMIN_EMAIL / ADMIN_PASSWORD : identifiants du 1er administrateur
  ENABLE_REGISTRATION  : "true"/"false" (inscription publique, défaut true)
"""

import runpy

import streamlit as st

# set_page_config DOIT être la première commande Streamlit appelée.
st.set_page_config(
    page_title="🌿 Plant Doctor",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="auto",
)

import auth          # noqa: E402
import database as db  # noqa: E402
from admin import render_admin  # noqa: E402
from user_profile import render_profile  # noqa: E402

APP_FILE = "plante_sante_app.py"  # application métier à protéger

# --------------------------------------------------------------------------- #
# Initialisation (exécutée UNE seule fois par processus, pas à chaque interaction)
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def _bootstrap_database():
    """Crée les tables et l'admin initial une seule fois (mise en cache)."""
    db.init_db()
    return auth.ensure_seed_admin()


seed_warning = _bootstrap_database()


# --------------------------------------------------------------------------- #
# Exécution de l'application métier sans rappeler set_page_config
# --------------------------------------------------------------------------- #
def run_app() -> None:
    """Exécute Plant Doctor en neutralisant son appel à set_page_config."""
    original = st.set_page_config
    st.set_page_config = lambda *a, **k: None  # déjà configuré par main.py
    try:
        runpy.run_path(APP_FILE, run_name="__main__")
    finally:
        st.set_page_config = original


# --------------------------------------------------------------------------- #
# Garde d'authentification
# --------------------------------------------------------------------------- #
if not auth.is_authenticated():
    if seed_warning:
        st.warning(seed_warning)
    auth.render_auth_page()
    st.stop()

user = auth.get_current_user()

# --------------------------------------------------------------------------- #
# Barre latérale : utilisateur, navigation, déconnexion
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"### 👤 {user['full_name'] or user['email']}")
    st.caption(f"Rôle : **{user['role']}**  ·  {user['email']}")
    st.divider()

    options = ["🌿 Application", "👤 Mon profil"]
    if user["role"] == "ADMIN":
        options.append("🛠️ Administration")
    page = st.radio("Navigation", options, key="nav_page")
    if user["role"] == "ADMIN":
        # Indicateur de la base de données active (visible par les ADMIN)
        st.caption(f"🗄️ Base : **{db.BACKEND}**")

    st.divider()
    if st.button("🚪 Se déconnecter", key="btn_logout"):
        auth.logout()
        st.rerun()

# --------------------------------------------------------------------------- #
# Routage
# --------------------------------------------------------------------------- #
page = st.session_state.get("nav_page", "🌿 Application")
if page == "🛠️ Administration" and user["role"] == "ADMIN":
    render_admin()
elif page == "👤 Mon profil":
    render_profile()
else:
    run_app()
