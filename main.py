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
from datetime import datetime, timedelta

import streamlit as st

# set_page_config DOIT être la première commande Streamlit appelée.
st.set_page_config(
    page_title="🌿 Plant Doctor",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="auto",
)

import extra_streamlit_components as stx  # noqa: E402
from streamlit_float import float_init, float_css_helper  # noqa: E402
import auth          # noqa: E402
import database as db  # noqa: E402
import i18n           # noqa: E402
from admin import render_admin  # noqa: E402
from user_profile import render_profile  # noqa: E402
from contact import render_contact  # noqa: E402
from disclaimer import render_disclaimer  # noqa: E402

float_init()

APP_FILE = "plante_sante_app.py"  # application métier à protéger
COOKIE_NAME = "pd_auth"

# --------------------------------------------------------------------------- #
# Initialisation
# --------------------------------------------------------------------------- #
# init_db() est idempotent et rapide (connexion persistante) : on l'exécute à
# chaque chargement pour garantir que les migrations de schéma sont appliquées.
db.init_db()


@st.cache_resource(show_spinner=False)
def _seed_admin():
    """Crée l'administrateur initial une seule fois (si la base est vide)."""
    return auth.ensure_seed_admin()


seed_warning = _seed_admin()


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
# « Rester connecté » : restauration de session via cookie
# --------------------------------------------------------------------------- #
cookie_manager = stx.CookieManager()
cookie_manager.get_all()  # charge les cookies du navigateur
remember_token = cookie_manager.get(COOKIE_NAME)

# Restaure la session depuis le cookie si la session Streamlit a été perdue
if not auth.is_authenticated() and remember_token:
    _u = auth.validate_remember_token(remember_token)
    if _u:
        auth.open_session_for(_u)

# --------------------------------------------------------------------------- #
# Garde d'authentification
# --------------------------------------------------------------------------- #
if not auth.is_authenticated():
    if seed_warning:
        st.warning(seed_warning)
    auth.render_auth_page()
    st.stop()

user = auth.get_current_user()

# Émet le cookie « rester connecté » après une connexion (une seule fois)
if remember_token is None and not st.session_state.get("_remember_set"):
    _raw = auth.create_remember_token(user["id"])
    cookie_manager.set(
        COOKIE_NAME, _raw,
        expires_at=datetime.utcnow() + timedelta(days=auth.REMEMBER_DAYS),
        key="set_auth_cookie",
    )
    st.session_state["_remember_set"] = True
st.session_state.setdefault("lang", "fr")   # langue par défaut
st.session_state.setdefault("nav_page", "accueil")
st.session_state["_under_main"] = True      # le globe in-app est remplacé par la sidebar


def _do_logout():
    auth.revoke_remember_token(remember_token)
    try:
        cookie_manager.delete(COOKIE_NAME, key="del_auth_cookie")
    except Exception:
        pass
    st.session_state.pop("_remember_set", None)
    auth.logout()
    st.rerun()


def render_more():
    """Page « Plus » : accès au profil, contact, disclaimer, admin, déconnexion."""
    st.markdown("## ➕ Plus")
    u = auth.get_current_user()
    st.markdown(f"**{u['full_name'] or u['email']}** · {u['role']}")
    i18n.language_popover(user_id=u["id"], key="more_lang")
    st.divider()
    liens = [("👤 Mon profil", "profil"), ("📨 Contact", "contact"), ("⚠️ Disclaimer", "disclaimer")]
    if u["role"] == "ADMIN":
        liens.append(("🛠️ Administration", "admin"))
    for label, cible in liens:
        if st.button(label, key=f"more_{cible}", use_container_width=True):
            st.session_state["nav_page"] = cible
            st.rerun()
    if u["role"] == "ADMIN":
        st.caption(f"🗄️ Base : **{db.BACKEND}**")
    st.divider()
    if st.button("🚪 Se déconnecter", key="more_logout", use_container_width=True):
        _do_logout()


# Styles : barre du bas + marge pour ne pas masquer le contenu
st.markdown(
    """
    <style>
      .block-container { padding-bottom: 6.5rem !important; }
      div[data-testid="stPopover"] button {
        background: linear-gradient(135deg, #16a34a, #22c55e) !important;
        color: #fff !important; border: none !important; border-radius: 12px !important; font-weight: 700 !important;
      }
      /* Onglets de la barre du bas (icône au-dessus du libellé) */
      .st-key-bn_accueil button, .st-key-bn_diag button,
      .st-key-bn_plantes button, .st-key-bn_plus button {
        background: transparent !important; color: #cfe8d6 !important; border: none !important;
        box-shadow: none !important; height: 3.2rem !important; font-size: .72rem !important;
        font-weight: 700 !important; line-height: 1.15 !important; padding: .2rem 0 !important;
        white-space: pre-line !important; transform: none !important;
      }
      .st-key-bn_accueil button:hover, .st-key-bn_diag button:hover,
      .st-key-bn_plantes button:hover, .st-key-bn_plus button:hover { color: #fff !important; }
      /* Bouton caméra central, surélevé et rond */
      .st-key-bn_cam button {
        background: linear-gradient(135deg, #16a34a, #22c55e) !important; color: #fff !important;
        border: none !important; border-radius: 50% !important;
        width: 4rem !important; height: 4rem !important; font-size: 1.5rem !important;
        margin: -1.3rem auto 0 !important; box-shadow: 0 6px 16px rgba(22,163,74,.45) !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Barre latérale : infos + langue (navigation principale = barre du bas)
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"### 👤 {user['full_name'] or user['email']}")
    st.caption(f"Rôle : **{user['role']}**  ·  {user['email']}")
    i18n.language_popover(user_id=user["id"], key="side_lang")
    if user["role"] == "ADMIN":
        st.caption(f"🗄️ Base : **{db.BACKEND}**")
    st.divider()
    if st.button("🚪 Se déconnecter", key="btn_logout"):
        _do_logout()

# --------------------------------------------------------------------------- #
# Routage
# --------------------------------------------------------------------------- #
nav = st.session_state.get("nav_page", "accueil")
st.session_state["focus_history"] = (nav == "plantes")

if nav == "plus":
    render_more()
elif nav == "profil":
    render_profile()
elif nav == "contact":
    render_contact()
elif nav == "disclaimer":
    render_disclaimer()
elif nav == "admin" and user["role"] == "ADMIN":
    render_admin()
else:  # accueil / diagnostic / plantes
    run_app()

# --------------------------------------------------------------------------- #
# Barre de navigation fixe en bas
# --------------------------------------------------------------------------- #
bottom_bar = st.container()
with bottom_bar:
    bcols = st.columns(5)
    if bcols[0].button("🏠\nAccueil", key="bn_accueil", use_container_width=True):
        st.session_state["nav_page"] = "accueil"
        st.session_state["camera_active"] = False
        st.rerun()
    if bcols[1].button("🩺\nDiagnostic", key="bn_diag", use_container_width=True):
        st.session_state["nav_page"] = "diagnostic"
        st.rerun()
    if bcols[2].button("📷", key="bn_cam", use_container_width=True):
        st.session_state["nav_page"] = "accueil"
        st.session_state["camera_active"] = True
        st.rerun()
    if bcols[3].button("🌱\nMes Plantes", key="bn_plantes", use_container_width=True):
        st.session_state["nav_page"] = "plantes"
        st.rerun()
    if bcols[4].button("➕\nPlus", key="bn_plus", use_container_width=True):
        st.session_state["nav_page"] = "plus"
        st.rerun()

bottom_bar.float(
    float_css_helper(
        bottom="0", left="0",
        background="rgba(20, 39, 26, 0.97)", z_index="9999",
        css="width:100%; padding:.1rem .4rem .3rem; box-shadow:0 -4px 16px rgba(0,0,0,.25); backdrop-filter:blur(4px);",
    )
)
