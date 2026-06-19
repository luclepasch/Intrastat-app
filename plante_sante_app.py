"""
🌿 Plant Doctor — Analyseur de santé des plantes
================================================

Application web optimisée pour smartphone : prenez une photo d'une plante avec
l'appareil photo de votre téléphone, l'IA de vision de Claude analyse son état
de santé et propose des solutions concrètes.

Lancement local :
    streamlit run plante_sante_app.py

Clé API requise : définissez la variable d'environnement ANTHROPIC_API_KEY,
ou ajoutez-la dans .streamlit/secrets.toml :
    ANTHROPIC_API_KEY = "sk-ant-..."
"""

import base64
import json
import os

import anthropic
import streamlit as st

# --------------------------------------------------------------------------- #
# Configuration de la page (mobile-first)
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="🌿 Plant Doctor",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed",
)

MODEL = "claude-opus-4-8"

# Quelques ajustements CSS pour un rendu agréable sur petit écran
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 720px; }
      .stButton button { width: 100%; border-radius: 12px; height: 3rem; font-size: 1.05rem; }
      div[data-testid="stMetricValue"] { font-size: 1.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Récupération de la clé API
# --------------------------------------------------------------------------- #
def get_api_key() -> str | None:
    """Cherche la clé API dans les secrets Streamlit puis l'environnement."""
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        # st.secrets lève une exception si aucun fichier secrets.toml n'existe
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


# --------------------------------------------------------------------------- #
# Schéma de sortie structurée (JSON garanti par l'API)
# --------------------------------------------------------------------------- #
SCHEMA = {
    "type": "object",
    "properties": {
        "est_une_plante": {
            "type": "boolean",
            "description": "True si l'image contient bien une plante analysable.",
        },
        "plante": {
            "type": "string",
            "description": "Nom commun probable de la plante (en français).",
        },
        "nom_latin": {
            "type": "string",
            "description": "Nom latin/botanique si identifiable, sinon chaîne vide.",
        },
        "etat_general": {
            "type": "string",
            "enum": ["Bon", "Moyen", "Mauvais", "Inconnu"],
            "description": "Évaluation globale de l'état de santé.",
        },
        "score_sante": {
            "type": "integer",
            "description": "Score de santé de 0 (mourante) à 100 (parfaite santé).",
        },
        "resume": {
            "type": "string",
            "description": "Résumé d'une à deux phrases sur l'état de la plante.",
        },
        "problemes": {
            "type": "array",
            "description": "Liste des problèmes détectés (maladies, parasites, carences, stress).",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Nom court du problème."},
                    "description": {
                        "type": "string",
                        "description": "Symptômes observés sur la photo et cause probable.",
                    },
                    "gravite": {
                        "type": "string",
                        "enum": ["Faible", "Modérée", "Élevée"],
                    },
                },
                "required": ["nom", "description", "gravite"],
                "additionalProperties": False,
            },
        },
        "solutions": {
            "type": "array",
            "description": "Actions concrètes pour soigner la plante, ordre de priorité.",
            "items": {"type": "string"},
        },
        "prevention": {
            "type": "array",
            "description": "Conseils d'entretien pour éviter que les problèmes reviennent.",
            "items": {"type": "string"},
        },
        "confiance": {
            "type": "string",
            "enum": ["Faible", "Moyenne", "Élevée"],
            "description": "Confiance du diagnostic compte tenu de la qualité de la photo.",
        },
    },
    "required": [
        "est_une_plante",
        "plante",
        "nom_latin",
        "etat_general",
        "score_sante",
        "resume",
        "problemes",
        "solutions",
        "prevention",
        "confiance",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Tu es un expert en phytopathologie et en horticulture. À partir d'une photo, "
    "tu identifies la plante, tu évalues son état de santé, tu détectes les maladies, "
    "parasites, carences nutritionnelles et stress (sur-arrosage, manque de lumière, etc.), "
    "puis tu proposes des solutions concrètes et réalisables par un particulier. "
    "Réponds toujours en français, de façon claire et bienveillante. "
    "Si l'image ne contient pas de plante, indique-le via le champ 'est_une_plante'. "
    "Base ton diagnostic uniquement sur ce qui est visible ; ajuste ta confiance "
    "selon la netteté et le cadrage de la photo."
)

MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def analyser_plante(client: anthropic.Anthropic, image_bytes: bytes, media_type: str) -> dict:
    """Envoie la photo à Claude et renvoie le diagnostic structuré (dict)."""
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Analyse l'état de santé de cette plante et propose des "
                            "solutions. Suis strictement le format JSON demandé."
                        ),
                    },
                ],
            }
        ],
    )

    text = next((b.text for b in response.content if b.type == "text"), "{}")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Rendu du diagnostic
# --------------------------------------------------------------------------- #
COULEUR_ETAT = {"Bon": "🟢", "Moyen": "🟡", "Mauvais": "🔴", "Inconnu": "⚪"}
COULEUR_GRAVITE = {"Faible": "🟢", "Modérée": "🟡", "Élevée": "🔴"}


def afficher_diagnostic(diag: dict) -> None:
    if not diag.get("est_une_plante", True):
        st.warning(
            "🤔 Je n'ai pas reconnu de plante sur cette photo. "
            "Essayez de cadrer plus près du feuillage, avec une bonne lumière."
        )
        return

    plante = diag.get("plante", "Plante inconnue")
    nom_latin = diag.get("nom_latin", "")
    titre = f"🪴 {plante}"
    if nom_latin:
        titre += f"  ·  *{nom_latin}*"
    st.markdown(f"### {titre}")

    if diag.get("resume"):
        st.write(diag["resume"])

    # Indicateurs clés
    col1, col2, col3 = st.columns(3)
    etat = diag.get("etat_general", "Inconnu")
    col1.metric("État général", f"{COULEUR_ETAT.get(etat, '⚪')} {etat}")
    score = int(diag.get("score_sante", 0))
    col2.metric("Score de santé", f"{score}/100")
    col3.metric("Confiance", diag.get("confiance", "—"))

    st.progress(max(0, min(100, score)) / 100)

    # Problèmes détectés
    problemes = diag.get("problemes", [])
    st.markdown("#### 🔍 Problèmes détectés")
    if not problemes:
        st.success("Aucun problème majeur détecté. Belle plante ! 🌟")
    else:
        for p in problemes:
            icone = COULEUR_GRAVITE.get(p.get("gravite", ""), "⚪")
            with st.expander(f"{icone} {p.get('nom', 'Problème')}  ·  Gravité : {p.get('gravite', '—')}"):
                st.write(p.get("description", ""))

    # Solutions
    solutions = diag.get("solutions", [])
    if solutions:
        st.markdown("#### 💊 Solutions recommandées")
        for i, s in enumerate(solutions, 1):
            st.markdown(f"**{i}.** {s}")

    # Prévention
    prevention = diag.get("prevention", [])
    if prevention:
        st.markdown("#### 🛡️ Conseils de prévention")
        for c in prevention:
            st.markdown(f"- {c}")

    st.caption(
        "⚠️ Diagnostic généré par une IA à titre indicatif. En cas de doute "
        "sur une plante de valeur, consultez un professionnel."
    )


# --------------------------------------------------------------------------- #
# Interface principale
# --------------------------------------------------------------------------- #
st.title("🌿 Plant Doctor")
st.caption("Prenez une photo de votre plante — l'IA analyse sa santé et propose des solutions.")

api_key = get_api_key()
if not api_key:
    st.error(
        "🔑 Aucune clé API Anthropic configurée.\n\n"
        "Définissez la variable d'environnement `ANTHROPIC_API_KEY`, "
        "ou créez le fichier `.streamlit/secrets.toml` avec :\n\n"
        "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```"
    )
    st.stop()

# Choix de la source de l'image : appareil photo ou galerie
source = st.radio(
    "Source de la photo",
    ["📷 Appareil photo", "🖼️ Depuis la galerie"],
    horizontal=True,
    label_visibility="collapsed",
)

image_bytes = None
media_type = "image/jpeg"

if source == "📷 Appareil photo":
    photo = st.camera_input("Prenez une photo de la plante")
    if photo is not None:
        image_bytes = photo.getvalue()
        media_type = photo.type or "image/jpeg"
else:
    fichier = st.file_uploader(
        "Choisissez une photo",
        type=list(MEDIA_TYPES.keys()),
        accept_multiple_files=False,
    )
    if fichier is not None:
        image_bytes = fichier.getvalue()
        ext = fichier.name.rsplit(".", 1)[-1].lower()
        media_type = MEDIA_TYPES.get(ext, "image/jpeg")
        st.image(image_bytes, caption="Photo sélectionnée", use_container_width=True)

if image_bytes:
    if st.button("🔬 Analyser la plante", type="primary"):
        client = anthropic.Anthropic(api_key=api_key)
        try:
            with st.spinner("Analyse en cours… 🌱"):
                diagnostic = analyser_plante(client, image_bytes, media_type)
            st.divider()
            afficher_diagnostic(diagnostic)
        except anthropic.AuthenticationError:
            st.error("Clé API invalide. Vérifiez votre `ANTHROPIC_API_KEY`.")
        except anthropic.RateLimitError:
            st.error("Trop de requêtes. Patientez quelques instants puis réessayez.")
        except anthropic.APIError as e:
            st.error(f"Erreur de l'API Claude : {e}")
        except (json.JSONDecodeError, KeyError):
            st.error("La réponse de l'IA n'a pas pu être interprétée. Réessayez avec une autre photo.")
else:
    st.info("👆 Prenez ou choisissez une photo pour démarrer l'analyse.")
