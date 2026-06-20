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
import streamlit.components.v1 as components  # noqa: E402
import auth          # noqa: E402
import database as db  # noqa: E402
import i18n           # noqa: E402
from admin import render_admin  # noqa: E402
from user_profile import render_profile  # noqa: E402
from contact import render_contact  # noqa: E402
from disclaimer import render_disclaimer  # noqa: E402

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

# --------------------------------------------------------------------------- #
# Navigation via la barre du bas (liens HTML -> paramètres d'URL)
# --------------------------------------------------------------------------- #
# La barre du bas est un bloc HTML pur (liens <a href="?nav=...">) : robuste sur
# tous les navigateurs mobiles, contrairement aux colonnes Streamlit.
if "nav" in st.query_params:
    st.session_state["nav_page"] = st.query_params.get("nav", "accueil")
    st.session_state["camera_active"] = (st.query_params.get("cam") == "1")
    st.query_params.clear()   # nettoie l'URL (déclenche un rerun)


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


# Styles : barre du bas (HTML pur) + marge pour ne pas masquer le contenu
st.markdown(
    """
    <style>
      /* --- Plein écran mobile : on masque le « chrome » Streamlit --- */
      div[data-testid="stToolbar"] { display: none !important; }
      div[data-testid="stDecoration"] { display: none !important; }
      div[data-testid="stStatusWidget"] { display: none !important; }
      #MainMenu { display: none !important; }
      footer { display: none !important; }
      header[data-testid="stHeader"] {
        background: transparent !important; height: 0 !important;
      }
      /* On récupère l'espace en haut et on respecte l'encoche (safe-area) */
      .block-container {
        padding-top: max(1rem, env(safe-area-inset-top)) !important;
        padding-bottom: calc(6.5rem + env(safe-area-inset-bottom)) !important;
        padding-left: max(1rem, env(safe-area-inset-left)) !important;
        padding-right: max(1rem, env(safe-area-inset-right)) !important;
      }
      div[data-testid="stPopover"] button {
        background: linear-gradient(135deg, #16a34a, #22c55e) !important;
        color: #fff !important; border: none !important; border-radius: 12px !important; font-weight: 700 !important;
      }
      /* Barre de navigation fixe en bas (flexbox, compatible tous navigateurs) */
      .pd-bottombar {
        position: fixed; left: 0; bottom: 0; width: 100%; z-index: 9999;
        display: flex; flex-direction: row; flex-wrap: nowrap;
        justify-content: space-around; align-items: flex-end;
        background: rgba(20, 39, 26, 0.97); backdrop-filter: blur(4px);
        box-shadow: 0 -4px 16px rgba(0,0,0,.25);
        padding: .3rem .3rem calc(.4rem + env(safe-area-inset-bottom));
      }
      .pd-bottombar a {
        flex: 1 1 0; min-width: 0; text-align: center; text-decoration: none;
        color: #cfe8d6; font-size: .7rem; font-weight: 700; line-height: 1.15;
        display: flex; flex-direction: column; align-items: center; gap: .15rem;
        padding: .2rem 0;
      }
      .pd-bottombar a:hover { color: #fff; }
      .pd-bottombar a .ic { font-size: 1.3rem; }
      /* Bouton caméra central, surélevé et rond */
      .pd-bottombar a.pd-cam { flex: 0 0 auto; }
      .pd-bottombar a.pd-cam .ic {
        background: linear-gradient(135deg, #16a34a, #22c55e); color: #fff;
        width: 3.7rem; height: 3.7rem; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        margin-top: -1.5rem; font-size: 1.5rem;
        box-shadow: 0 6px 16px rgba(22,163,74,.45);
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Plein écran mobile (PWA) : balises <head> pour un affichage « standalone »
# --------------------------------------------------------------------------- #
# st.markdown n'écrit que dans le <body> ; on injecte donc les balises <meta>
# dans le <head> du document parent via un petit script (idempotent).
components.html(
    """
    <script>
      try {
      const head = window.parent.document.head;
      const metas = {
        "viewport": "width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover",
        "apple-mobile-web-app-capable": "yes",
        "mobile-web-app-capable": "yes",
        "apple-mobile-web-app-status-bar-style": "black-translucent",
        "apple-mobile-web-app-title": "Plant Doctor",
        "theme-color": "#14271a"
      };
      for (const [name, content] of Object.entries(metas)) {
        let tag = head.querySelector('meta[name="' + name + '"]');
        if (!tag) {
          tag = window.parent.document.createElement('meta');
          tag.setAttribute('name', name);
          head.appendChild(tag);
        }
        tag.setAttribute('content', content);
      }
      } catch (e) { /* head du parent inaccessible : on ignore */ }
    </script>
    """,
    height=0,
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
# Barre de navigation fixe en bas (HTML pur : liens vers ?nav=...)
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <div class="pd-bottombar">
      <a href="?nav=accueil" target="_self"><span class="ic">🏠</span>Accueil</a>
      <a href="?nav=diagnostic" target="_self"><span class="ic">🩺</span>Diagnostic</a>
      <a class="pd-cam" href="?nav=accueil&amp;cam=1" target="_self"><span class="ic">📷</span></a>
      <a href="?nav=plantes" target="_self"><span class="ic">🌱</span>Plantes</a>
      <a href="?nav=plus" target="_self"><span class="ic">➕</span>Plus</a>
    </div>
    """,
    unsafe_allow_html=True,
)
