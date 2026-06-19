"""
🌿 Plant Doctor — Analyseur de santé des plantes
================================================

Application web optimisée pour smartphone : prenez une ou plusieurs photos d'une
plante (jusqu'à 4, sous différents angles), l'IA de vision de Claude analyse en
détail son état de santé, propose des solutions concrètes et illustre le
diagnostic (dessin schématique + photos d'exemples).

Lancement local :
    streamlit run plante_sante_app.py

Clé API requise : définissez la variable d'environnement ANTHROPIC_API_KEY,
ou ajoutez-la dans .streamlit/secrets.toml :
    ANTHROPIC_API_KEY = "sk-ant-..."
"""

import base64
import hashlib
import json
import os
import urllib.parse

import anthropic
import streamlit as st
import streamlit.components.v1 as components

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
MAX_PHOTOS = 4

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
            "description": "True si les images contiennent bien une plante analysable.",
        },
        "plante": {"type": "string", "description": "Nom commun probable (en français)."},
        "nom_latin": {"type": "string", "description": "Nom latin/botanique, sinon chaîne vide."},
        "famille": {"type": "string", "description": "Famille botanique, sinon chaîne vide."},
        "etat_general": {
            "type": "string",
            "enum": ["Bon", "Moyen", "Mauvais", "Inconnu"],
        },
        "score_sante": {
            "type": "integer",
            "description": "Score de santé de 0 (mourante) à 100 (parfaite santé).",
        },
        "resume": {"type": "string", "description": "Résumé d'une à deux phrases."},
        "identification_details": {
            "type": "string",
            "description": "Caractéristiques visibles ayant permis l'identification (feuilles, port, fleurs…).",
        },
        "analyse_detaillee": {
            "type": "string",
            "description": "Analyse approfondie combinant TOUTES les photos fournies (2-4 phrases riches).",
        },
        "conditions_culture": {
            "type": "object",
            "description": "État/conseils sur les conditions de culture, déduits des photos.",
            "properties": {
                "arrosage": {"type": "string"},
                "lumiere": {"type": "string"},
                "temperature_humidite": {"type": "string"},
                "substrat_engrais": {"type": "string"},
            },
            "required": ["arrosage", "lumiere", "temperature_humidite", "substrat_engrais"],
            "additionalProperties": False,
        },
        "problemes": {
            "type": "array",
            "description": "Problèmes détectés (maladies, parasites, carences, stress).",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Nom court du problème."},
                    "symptomes": {"type": "string", "description": "Symptômes précis observés sur les photos."},
                    "cause": {"type": "string", "description": "Cause probable."},
                    "gravite": {"type": "string", "enum": ["Faible", "Modérée", "Élevée"]},
                    "traitement": {
                        "type": "array",
                        "description": "Étapes de traitement concrètes pour ce problème.",
                        "items": {"type": "string"},
                    },
                    "terme_recherche_image": {
                        "type": "string",
                        "description": "Terme court pour rechercher des photos d'exemples (ex: 'oïdium feuille rosier').",
                    },
                },
                "required": ["nom", "symptomes", "cause", "gravite", "traitement", "terme_recherche_image"],
                "additionalProperties": False,
            },
        },
        "solutions": {
            "type": "array",
            "description": "Plan d'action prioritaire (du plus urgent au moins urgent).",
            "items": {"type": "string"},
        },
        "prevention": {
            "type": "array",
            "description": "Conseils pour éviter que les problèmes reviennent.",
            "items": {"type": "string"},
        },
        "calendrier_entretien": {
            "type": "array",
            "description": "Routine d'entretien recommandée (gestes réguliers).",
            "items": {"type": "string"},
        },
        "illustration_svg": {
            "type": "string",
            "description": (
                "Un dessin schématique SVG simple et lisible (viewBox, max ~400x360) illustrant la plante "
                "et localisant les zones atteintes avec de courtes étiquettes en français. "
                "SVG valide et autonome, sans script. Chaîne vide si non pertinent."
            ),
        },
        "confiance": {
            "type": "string",
            "enum": ["Faible", "Moyenne", "Élevée"],
            "description": "Confiance du diagnostic selon la qualité et le nombre de photos.",
        },
    },
    "required": [
        "est_une_plante", "plante", "nom_latin", "famille", "etat_general",
        "score_sante", "resume", "identification_details", "analyse_detaillee",
        "conditions_culture", "problemes", "solutions", "prevention",
        "calendrier_entretien", "illustration_svg", "confiance",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Tu es un expert en phytopathologie et en horticulture. À partir d'UNE OU PLUSIEURS photos "
    "de la MÊME plante (prises sous différents angles : plante entière, feuilles, tiges, racines, "
    "fleurs…), tu réalises un diagnostic détaillé. Croise les informations de toutes les photos "
    "pour identifier la plante, évaluer son état de santé, et détecter maladies, parasites, "
    "carences nutritionnelles et stress (sur-arrosage, manque de lumière, etc.). "
    "Tu proposes des solutions concrètes, réalisables par un particulier. "
    "Sois précis, pédagogique et bienveillant. Réponds toujours en français. "
    "Si les images ne contiennent pas de plante, indique-le via 'est_une_plante'. "
    "Base ton diagnostic uniquement sur ce qui est visible ; ajuste ta confiance selon la "
    "netteté, le cadrage et le nombre de photos."
)

MEDIA_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}


def analyser_plante(client: anthropic.Anthropic, photos: list[tuple[bytes, str]]) -> dict:
    """Envoie toutes les photos à Claude et renvoie le diagnostic structuré (dict)."""
    content = []
    for image_bytes, media_type in photos:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"Voici {len(photos)} photo(s) de la même plante. Analyse en détail son état de "
                "santé en croisant toutes les images, et propose des solutions. "
                "Suis strictement le format JSON demandé."
            ),
        }
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4500,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Rendu du diagnostic
# --------------------------------------------------------------------------- #
COULEUR_ETAT = {"Bon": "🟢", "Moyen": "🟡", "Mauvais": "🔴", "Inconnu": "⚪"}
COULEUR_GRAVITE = {"Faible": "🟢", "Modérée": "🟡", "Élevée": "🔴"}


def lien_images(terme: str) -> str:
    """Construit un lien de recherche de photos d'exemples (Google Images)."""
    q = urllib.parse.quote_plus(terme)
    return f"https://www.google.com/search?tbm=isch&q={q}"


def afficher_diagnostic(diag: dict) -> None:
    if not diag.get("est_une_plante", True):
        st.warning(
            "🤔 Je n'ai pas reconnu de plante sur ces photos. "
            "Essayez de cadrer plus près du feuillage, avec une bonne lumière."
        )
        return

    plante = diag.get("plante", "Plante inconnue")
    nom_latin = diag.get("nom_latin", "")
    famille = diag.get("famille", "")
    titre = f"🪴 {plante}"
    if nom_latin:
        titre += f"  ·  *{nom_latin}*"
    st.markdown(f"### {titre}")
    if famille:
        st.caption(f"Famille : {famille}")
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

    # Illustration (dessin schématique généré par l'IA)
    svg = diag.get("illustration_svg", "").strip()
    if svg.startswith("<svg"):
        st.markdown("#### 🖼️ Schéma illustré")
        components.html(
            f'<div style="display:flex;justify-content:center;">{svg}</div>',
            height=380,
        )

    # Identification & analyse détaillée
    if diag.get("identification_details") or diag.get("analyse_detaillee"):
        with st.expander("🔬 Identification & analyse détaillée", expanded=True):
            if diag.get("identification_details"):
                st.markdown("**Identification :**")
                st.write(diag["identification_details"])
            if diag.get("analyse_detaillee"):
                st.markdown("**Analyse :**")
                st.write(diag["analyse_detaillee"])

    # Conditions de culture
    cc = diag.get("conditions_culture", {})
    if cc:
        st.markdown("#### 🌡️ Conditions de culture")
        cca, ccb = st.columns(2)
        cca.markdown(f"💧 **Arrosage**\n\n{cc.get('arrosage', '—')}")
        cca.markdown(f"☀️ **Lumière**\n\n{cc.get('lumiere', '—')}")
        ccb.markdown(f"🌡️ **Température / humidité**\n\n{cc.get('temperature_humidite', '—')}")
        ccb.markdown(f"🪴 **Substrat / engrais**\n\n{cc.get('substrat_engrais', '—')}")

    # Problèmes détectés
    problemes = diag.get("problemes", [])
    st.markdown("#### 🔍 Problèmes détectés")
    if not problemes:
        st.success("Aucun problème majeur détecté. Belle plante ! 🌟")
    else:
        for p in problemes:
            icone = COULEUR_GRAVITE.get(p.get("gravite", ""), "⚪")
            with st.expander(f"{icone} {p.get('nom', 'Problème')}  ·  Gravité : {p.get('gravite', '—')}"):
                if p.get("symptomes"):
                    st.markdown(f"**Symptômes :** {p['symptomes']}")
                if p.get("cause"):
                    st.markdown(f"**Cause probable :** {p['cause']}")
                traitement = p.get("traitement", [])
                if traitement:
                    st.markdown("**Traitement :**")
                    for t in traitement:
                        st.markdown(f"- {t}")
                terme = p.get("terme_recherche_image") or p.get("nom", "")
                if terme:
                    st.markdown(
                        f"📷 [Voir des photos d'exemples de « {terme} »]({lien_images(terme)})"
                    )

    # Plan d'action
    solutions = diag.get("solutions", [])
    if solutions:
        st.markdown("#### 💊 Plan d'action prioritaire")
        for i, s in enumerate(solutions, 1):
            st.markdown(f"**{i}.** {s}")

    # Prévention
    prevention = diag.get("prevention", [])
    if prevention:
        st.markdown("#### 🛡️ Conseils de prévention")
        for c in prevention:
            st.markdown(f"- {c}")

    # Calendrier d'entretien
    calendrier = diag.get("calendrier_entretien", [])
    if calendrier:
        st.markdown("#### 🗓️ Routine d'entretien")
        for c in calendrier:
            st.markdown(f"- {c}")

    # Photos de référence de la plante
    terme_plante = " ".join(x for x in [plante, nom_latin] if x).strip()
    if terme_plante:
        st.markdown(
            f"🌿 [Voir des photos de référence de « {terme_plante} »]({lien_images(terme_plante)})"
        )

    st.caption(
        "⚠️ Diagnostic généré par une IA à titre indicatif. En cas de doute sur une plante "
        "de valeur, consultez un professionnel."
    )


# --------------------------------------------------------------------------- #
# Gestion des photos (accumulation de plusieurs images)
# --------------------------------------------------------------------------- #
def _empreinte(image_bytes: bytes) -> str:
    return hashlib.md5(image_bytes).hexdigest()


def ajouter_photo(image_bytes: bytes, media_type: str) -> bool:
    """Ajoute une photo à la sélection si elle n'y est pas déjà. Renvoie True si ajoutée."""
    photos = st.session_state.setdefault("photos", [])
    empreinte = _empreinte(image_bytes)
    if any(p["id"] == empreinte for p in photos):
        return False
    if len(photos) >= MAX_PHOTOS:
        return False
    photos.append({"id": empreinte, "bytes": image_bytes, "media_type": media_type})
    return True


# --------------------------------------------------------------------------- #
# Interface principale
# --------------------------------------------------------------------------- #
st.title("🌿 Plant Doctor")
st.caption(
    "Prenez plusieurs photos de votre plante (sous différents angles) — "
    "l'IA analyse sa santé en détail et propose des solutions illustrées."
)

api_key = get_api_key()
if not api_key:
    st.error(
        "🔑 Aucune clé API Anthropic configurée.\n\n"
        "Définissez la variable d'environnement `ANTHROPIC_API_KEY`, "
        "ou créez le fichier `.streamlit/secrets.toml` avec :\n\n"
        "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```"
    )
    st.stop()

st.session_state.setdefault("photos", [])

st.markdown(
    f"**Ajoutez jusqu'à {MAX_PHOTOS} photos** de la même plante "
    "(vue d'ensemble, feuilles, tiges, racines, zones abîmées…)."
)

source = st.radio(
    "Source de la photo",
    ["📷 Appareil photo", "🖼️ Depuis la galerie"],
    horizontal=True,
    label_visibility="collapsed",
)

if source == "📷 Appareil photo":
    photo = st.camera_input("Prenez une photo de la plante")
    if photo is not None:
        if st.button("➕ Ajouter cette photo à l'analyse"):
            if ajouter_photo(photo.getvalue(), photo.type or "image/jpeg"):
                st.success("Photo ajoutée ✅")
            else:
                st.info(f"Photo déjà ajoutée ou maximum de {MAX_PHOTOS} atteint.")
else:
    fichiers = st.file_uploader(
        "Choisissez une ou plusieurs photos",
        type=list(MEDIA_TYPES.keys()),
        accept_multiple_files=True,
    )
    if fichiers:
        ajoutees = 0
        for fichier in fichiers:
            ext = fichier.name.rsplit(".", 1)[-1].lower()
            if ajouter_photo(fichier.getvalue(), MEDIA_TYPES.get(ext, "image/jpeg")):
                ajoutees += 1
        if ajoutees:
            st.success(f"{ajoutees} photo(s) ajoutée(s) ✅")

# Galerie des photos sélectionnées
photos = st.session_state.get("photos", [])
if photos:
    st.markdown(f"**{len(photos)} / {MAX_PHOTOS} photo(s) sélectionnée(s) :**")
    cols = st.columns(min(len(photos), 4))
    for i, p in enumerate(photos):
        with cols[i % len(cols)]:
            st.image(p["bytes"], use_container_width=True)
            if st.button("🗑️ Retirer", key=f"del_{p['id']}"):
                st.session_state["photos"] = [x for x in photos if x["id"] != p["id"]]
                st.rerun()

    col_a, col_b = st.columns(2)
    lancer = col_a.button("🔬 Analyser la plante", type="primary")
    if col_b.button("♻️ Tout effacer"):
        st.session_state["photos"] = []
        st.rerun()

    if lancer:
        client = anthropic.Anthropic(api_key=api_key)
        try:
            with st.spinner(f"Analyse de {len(photos)} photo(s) en cours… 🌱"):
                diagnostic = analyser_plante(
                    client, [(p["bytes"], p["media_type"]) for p in photos]
                )
            st.divider()
            afficher_diagnostic(diagnostic)
        except anthropic.AuthenticationError:
            st.error("Clé API invalide. Vérifiez votre `ANTHROPIC_API_KEY`.")
        except anthropic.RateLimitError:
            st.error("Trop de requêtes. Patientez quelques instants puis réessayez.")
        except anthropic.APIError as e:
            st.error(f"Erreur de l'API Claude : {e}")
        except (json.JSONDecodeError, KeyError):
            st.error("La réponse de l'IA n'a pas pu être interprétée. Réessayez avec d'autres photos.")
else:
    st.info("👆 Ajoutez au moins une photo pour démarrer l'analyse.")
