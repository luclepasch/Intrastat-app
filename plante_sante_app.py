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
from streamlit_back_camera_input import back_camera_input

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
VERSION = "1.7"
VERSION_DATE = "juin 2026"

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap');

      html, body, [class*="css"] { font-family: 'Nunito', sans-serif; }

      /* Fond doux dégradé nature */
      .stApp {
        background: linear-gradient(180deg, #f4fbf5 0%, #ffffff 45%);
      }
      .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 760px; }

      /* En-tête héro */
      .hero {
        background: linear-gradient(135deg, #15803d 0%, #22c55e 55%, #4ade80 100%);
        border-radius: 22px;
        padding: 1.6rem 1.4rem;
        color: #ffffff;
        box-shadow: 0 12px 30px rgba(22, 163, 74, 0.28);
        margin-bottom: 1.4rem;
      }
      .hero h1 { margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.5px; }
      .hero p { margin: .35rem 0 0; font-size: 1rem; opacity: .95; font-weight: 600; }

      /* Boutons */
      .stButton button {
        width: 100%; border-radius: 14px; height: 3rem; font-size: 1.05rem;
        font-weight: 700; border: none;
        background: linear-gradient(135deg, #16a34a, #22c55e);
        color: #fff; transition: transform .08s ease, box-shadow .2s ease;
        box-shadow: 0 6px 16px rgba(22,163,74,.25);
      }
      .stButton button:hover { transform: translateY(-1px); box-shadow: 0 10px 22px rgba(22,163,74,.35); color:#fff; }
      .stButton button:active { transform: translateY(0); }

      /* Cartes métriques */
      div[data-testid="stMetric"] {
        background: #ffffff; border: 1px solid #d9efdd; border-radius: 16px;
        padding: .9rem .7rem; box-shadow: 0 4px 14px rgba(20,39,26,.05); text-align: center;
      }
      div[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 800; color: #15803d; }
      div[data-testid="stMetricLabel"] { justify-content: center; font-weight: 700; color:#436b4d; }

      /* Barre de progression */
      .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #f59e0b, #22c55e);
      }

      /* Expanders en cartes */
      [data-testid="stExpander"] {
        border: 1px solid #d9efdd; border-radius: 16px; overflow: hidden;
        box-shadow: 0 4px 14px rgba(20,39,26,.05); background:#fff; margin-bottom:.5rem;
      }
      [data-testid="stExpander"] summary { font-weight: 700; }

      /* Images arrondies */
      div[data-testid="stImage"] img { border-radius: 14px; }

      /* Titres de section */
      h4 { color: #15803d; font-weight: 800; margin-top: 1.3rem; }

      /* Radio en pilules */
      div[role="radiogroup"] label {
        background:#fff; border:1px solid #d9efdd; border-radius:999px;
        padding:.3rem .9rem; margin-right:.4rem; font-weight:700;
      }

      /* Empêche tout débordement horizontal (iframes de composants, médias) */
      iframe, img, video, svg { max-width: 100% !important; }
      .stApp { overflow-x: hidden; }

      /* ---- Adaptations smartphone ---- */
      @media (max-width: 640px) {
        .block-container { padding-left: .8rem; padding-right: .8rem; }
        .hero { padding: 1.2rem 1rem; border-radius: 18px; }
        .hero h1 { font-size: 1.55rem; }
        .hero p { font-size: .9rem; }
        h4 { font-size: 1.05rem; }

        /* Cartes métriques compactes et toujours lisibles sur 3 colonnes */
        div[data-testid="stMetric"] { padding: .55rem .35rem; }
        div[data-testid="stMetricValue"] { font-size: 1.1rem; }
        div[data-testid="stMetricLabel"] p { font-size: .72rem; }

        /* Les colonnes passent en pleine largeur (empilées) */
        div[data-testid="stHorizontalBlock"] { gap: .5rem; }
        .stButton button { font-size: 1rem; height: 2.8rem; }
      }
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
            "description": "Conseils de culture adaptés à cette plante, déduits aussi des photos.",
            "properties": {
                "arrosage": {
                    "type": "object",
                    "description": "Conseils d'arrosage adaptés à l'espèce et à la saison.",
                    "properties": {
                        "frequence": {
                            "type": "string",
                            "description": "À quelle fréquence arroser (ex: 'tous les 7-10 jours en été').",
                        },
                        "methode": {
                            "type": "string",
                            "description": "Comment arroser (quantité, par le haut/bas, eau, drainage…).",
                        },
                        "signes_de_manque": {
                            "type": "string",
                            "description": "Signes visibles d'un manque d'eau.",
                        },
                        "signes_d_exces": {
                            "type": "string",
                            "description": "Signes visibles d'un excès d'eau / sur-arrosage.",
                        },
                    },
                    "required": ["frequence", "methode", "signes_de_manque", "signes_d_exces"],
                    "additionalProperties": False,
                },
                "lumiere": {
                    "type": "object",
                    "description": "Conseils d'exposition à la lumière adaptés à l'espèce.",
                    "properties": {
                        "exposition": {
                            "type": "string",
                            "description": "Exposition idéale (plein soleil, mi-ombre, lumière vive indirecte, ombre…).",
                        },
                        "emplacement": {
                            "type": "string",
                            "description": "Où placer la plante (ex: 'près d'une fenêtre orientée est').",
                        },
                        "duree": {
                            "type": "string",
                            "description": "Durée/intensité de lumière recommandée par jour.",
                        },
                        "a_eviter": {
                            "type": "string",
                            "description": "Expositions à éviter (ex: soleil direct brûlant derrière une vitre).",
                        },
                        "signes_mauvais_eclairage": {
                            "type": "string",
                            "description": "Signes d'un manque ou d'un excès de lumière.",
                        },
                    },
                    "required": ["exposition", "emplacement", "duree", "a_eviter", "signes_mauvais_eclairage"],
                    "additionalProperties": False,
                },
                "temperature_humidite": {"type": "string"},
                "engrais": {
                    "type": "object",
                    "description": "Conseils de fertilisation adaptés à l'espèce.",
                    "properties": {
                        "type_recommande": {
                            "type": "string",
                            "description": "Type d'engrais conseillé (ex: 'engrais liquide riche en potassium').",
                        },
                        "frequence": {
                            "type": "string",
                            "description": "À quelle fréquence fertiliser (ex: 'tous les 15 jours au printemps/été').",
                        },
                        "periode": {
                            "type": "string",
                            "description": "Période de l'année où fertiliser / où s'arrêter.",
                        },
                        "precautions": {
                            "type": "string",
                            "description": "Précautions (diluer, ne pas fertiliser une plante stressée, etc.).",
                        },
                    },
                    "required": ["type_recommande", "frequence", "periode", "precautions"],
                    "additionalProperties": False,
                },
                "substrat": {
                    "type": "object",
                    "description": "Substrats adaptés à cette plante.",
                    "properties": {
                        "melange_ideal": {
                            "type": "string",
                            "description": "Composition de substrat idéale (ex: '2/3 terreau + 1/3 perlite').",
                        },
                        "conseilles": {
                            "type": "array",
                            "description": "Substrats/composants conseillés.",
                            "items": {"type": "string"},
                        },
                        "deconseilles": {
                            "type": "array",
                            "description": "Substrats/composants à éviter.",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["melange_ideal", "conseilles", "deconseilles"],
                    "additionalProperties": False,
                },
            },
            "required": ["arrosage", "lumiere", "temperature_humidite", "engrais", "substrat"],
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
        "astuces_grand_mere": {
            "type": "array",
            "description": (
                "Remèdes et astuces naturels traditionnels ('de grand-mère') adaptés à cette "
                "plante : marc de café, coquilles d'œuf, savon noir, peau de banane, eau de "
                "cuisson, purin d'ortie, etc. Explique brièvement l'usage pour chaque astuce."
            ),
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
        "calendrier_entretien", "astuces_grand_mere", "illustration_svg", "confiance",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Tu es un expert en phytopathologie et en horticulture. À partir d'UNE OU PLUSIEURS photos "
    "de la MÊME plante (prises sous différents angles : plante entière, feuilles, tiges, racines, "
    "fleurs…), tu réalises un diagnostic détaillé. Croise les informations de toutes les photos "
    "pour identifier la plante, évaluer son état de santé, et détecter maladies, parasites, "
    "carences nutritionnelles et stress (sur-arrosage, manque de lumière, etc.). "
    "Tu proposes des solutions concrètes, réalisables par un particulier, ainsi que "
    "des conseils d'arrosage précis (fréquence, méthode, signes de manque/d'excès) et "
    "des recommandations de substrats adaptés à l'espèce (mélange idéal, composants "
    "conseillés et à éviter), des conseils d'exposition à la lumière (exposition idéale, "
    "emplacement, durée, à éviter, signes d'un mauvais éclairage), des conseils de "
    "fertilisation (type d'engrais, fréquence, période, précautions), ainsi que des "
    "astuces naturelles traditionnelles ('de grand-mère') pertinentes pour cette plante. "
    "Sois précis, pédagogique et bienveillant. Réponds toujours en français. "
    "Si les images ne contiennent pas de plante, indique-le via 'est_une_plante'. "
    "Base ton diagnostic uniquement sur ce qui est visible ; ajuste ta confiance selon la "
    "netteté, le cadrage et le nombre de photos."
)

MEDIA_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}


def detecter_media_type(b: bytes) -> str:
    """Détecte le type MIME d'une image à partir de ses premiers octets."""
    if b[:8].startswith(b"\x89PNG"):
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


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
        max_tokens=5500,
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

# Remplacements pour rendre le texte compatible avec les polices PDF de base (latin-1)
_PDF_REMP = {
    "œ": "oe", "Œ": "OE", "æ": "ae", "—": "-", "–": "-", "’": "'", "‘": "'",
    "“": '"', "”": '"', "…": "...", "•": "-", "→": "->", "≈": "~",
}


def _pdf_txt(s) -> str:
    s = str(s)
    for k, v in _PDF_REMP.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def generer_pdf(diag: dict) -> bytes:
    """Génère une fiche PDF du diagnostic."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    vert = (21, 128, 61)

    def _line(txt, h):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, _pdf_txt(txt), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def titre(txt, size):
        pdf.set_font("Helvetica", "B", size)
        pdf.set_text_color(*vert)
        _line(txt, 8)
        pdf.set_text_color(0, 0, 0)

    def para(txt, bold=False, size=11):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        _line(txt, 6)

    def puce(txt):
        pdf.set_font("Helvetica", "", 11)
        _line("  - " + txt, 6)

    titre("Plant Doctor - Diagnostic", 18)
    sous = diag.get("plante", "Plante")
    if diag.get("nom_latin"):
        sous += f" ({diag['nom_latin']})"
    para(sous, bold=True, size=13)
    if diag.get("famille"):
        para(f"Famille : {diag['famille']}")
    para(
        f"Etat : {diag.get('etat_general', '-')}   |   "
        f"Score : {diag.get('score_sante', 0)}/100   |   "
        f"Confiance : {diag.get('confiance', '-')}"
    )
    if diag.get("resume"):
        para(diag["resume"])
    pdf.ln(2)

    if diag.get("identification_details"):
        titre("Identification", 13)
        para(diag["identification_details"])
    if diag.get("analyse_detaillee"):
        titre("Analyse detaillee", 13)
        para(diag["analyse_detaillee"])

    cc = diag.get("conditions_culture", {})
    if cc:
        titre("Conditions de culture", 13)
        arr = cc.get("arrosage", {})
        if isinstance(arr, dict) and any(arr.values()):
            para("Arrosage :", bold=True)
            for lbl, key in [("Frequence", "frequence"), ("Methode", "methode"),
                             ("Signes de manque", "signes_de_manque"),
                             ("Signes d'exces", "signes_d_exces")]:
                if arr.get(key):
                    puce(f"{lbl} : {arr[key]}")
        lum = cc.get("lumiere", {})
        if isinstance(lum, dict) and any(lum.values()):
            para("Exposition a la lumiere :", bold=True)
            for lbl, key in [("Exposition", "exposition"), ("Emplacement", "emplacement"),
                             ("Duree", "duree"), ("A eviter", "a_eviter"),
                             ("Signes mauvais eclairage", "signes_mauvais_eclairage")]:
                if lum.get(key):
                    puce(f"{lbl} : {lum[key]}")
        if cc.get("temperature_humidite"):
            para("Temperature / humidite :", bold=True)
            puce(cc["temperature_humidite"])
        eng = cc.get("engrais", {})
        if isinstance(eng, dict) and any(eng.values()):
            para("Fertilisation / engrais :", bold=True)
            for lbl, key in [("Type recommande", "type_recommande"), ("Frequence", "frequence"),
                             ("Periode", "periode"), ("Precautions", "precautions")]:
                if eng.get(key):
                    puce(f"{lbl} : {eng[key]}")
        sub = cc.get("substrat", {})
        if isinstance(sub, dict) and any(sub.values()):
            para("Substrat :", bold=True)
            if sub.get("melange_ideal"):
                puce(f"Melange ideal : {sub['melange_ideal']}")
            for s in sub.get("conseilles", []):
                puce(f"Conseille : {s}")
            for s in sub.get("deconseilles", []):
                puce(f"A eviter : {s}")

    problemes = diag.get("problemes", [])
    if problemes:
        titre("Problemes detectes", 13)
        for p in problemes:
            para(f"{p.get('nom', 'Probleme')} (gravite : {p.get('gravite', '-')})", bold=True)
            if p.get("symptomes"):
                puce(f"Symptomes : {p['symptomes']}")
            if p.get("cause"):
                puce(f"Cause : {p['cause']}")
            for t in p.get("traitement", []):
                puce(f"Traitement : {t}")

    for cle, titre_section in [
        ("solutions", "Plan d'action prioritaire"),
        ("prevention", "Conseils de prevention"),
        ("calendrier_entretien", "Routine d'entretien"),
        ("astuces_grand_mere", "Astuces de grand-mere"),
    ]:
        items = diag.get(cle, [])
        if items:
            titre(titre_section, 13)
            for it in items:
                puce(it)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(
        0, 5,
        _pdf_txt(f"Plant Doctor v{VERSION} - Diagnostic genere par IA, a titre indicatif."),
    )
    return bytes(pdf.output())


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
            "<div style='display:flex;justify-content:center;align-items:center;"
            "width:100%;'>"
            "<style>svg{width:100%;height:auto;max-width:360px;}</style>"
            f"{svg}</div>",
            height=340,
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

        # Arrosage détaillé
        arr = cc.get("arrosage", {})
        if isinstance(arr, dict):
            with st.expander("💧 Conseils d'arrosage", expanded=True):
                if arr.get("frequence"):
                    st.markdown(f"**Fréquence :** {arr['frequence']}")
                if arr.get("methode"):
                    st.markdown(f"**Méthode :** {arr['methode']}")
                if arr.get("signes_de_manque"):
                    st.markdown(f"🥵 **Signes de manque d'eau :** {arr['signes_de_manque']}")
                if arr.get("signes_d_exces"):
                    st.markdown(f"💦 **Signes d'excès d'eau :** {arr['signes_d_exces']}")
        elif arr:
            st.markdown(f"💧 **Arrosage :** {arr}")

        # Substrat conseillé / déconseillé
        sub = cc.get("substrat", {})
        if isinstance(sub, dict):
            with st.expander("🪴 Substrats conseillés & déconseillés", expanded=True):
                if sub.get("melange_ideal"):
                    st.markdown(f"🌱 **Mélange idéal :** {sub['melange_ideal']}")
                if sub.get("conseilles"):
                    st.markdown("✅ **Conseillés :**")
                    for s in sub["conseilles"]:
                        st.markdown(f"- {s}")
                if sub.get("deconseilles"):
                    st.markdown("🚫 **À éviter :**")
                    for s in sub["deconseilles"]:
                        st.markdown(f"- {s}")
        elif sub:
            st.markdown(f"🪴 **Substrat :** {sub}")

        # Exposition à la lumière
        lum = cc.get("lumiere", {})
        if isinstance(lum, dict):
            with st.expander("☀️ Exposition à la lumière", expanded=True):
                if lum.get("exposition"):
                    st.markdown(f"**Exposition idéale :** {lum['exposition']}")
                if lum.get("emplacement"):
                    st.markdown(f"📍 **Emplacement :** {lum['emplacement']}")
                if lum.get("duree"):
                    st.markdown(f"⏱️ **Durée / intensité :** {lum['duree']}")
                if lum.get("a_eviter"):
                    st.markdown(f"🚫 **À éviter :** {lum['a_eviter']}")
                if lum.get("signes_mauvais_eclairage"):
                    st.markdown(f"🔎 **Signes d'un mauvais éclairage :** {lum['signes_mauvais_eclairage']}")
        elif lum:
            st.markdown(f"☀️ **Lumière :** {lum}")

        # Température / humidité
        st.markdown(f"🌡️ **Température / humidité :** {cc.get('temperature_humidite', '—')}")

        # Fertilisation / engrais
        eng = cc.get("engrais", {})
        if isinstance(eng, dict) and any(eng.values()):
            with st.expander("🧪 Fertilisation / engrais", expanded=True):
                if eng.get("type_recommande"):
                    st.markdown(f"**Type recommandé :** {eng['type_recommande']}")
                if eng.get("frequence"):
                    st.markdown(f"**Fréquence :** {eng['frequence']}")
                if eng.get("periode"):
                    st.markdown(f"📅 **Période :** {eng['periode']}")
                if eng.get("precautions"):
                    st.markdown(f"⚠️ **Précautions :** {eng['precautions']}")

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

    # Astuces de grand-mère
    astuces = diag.get("astuces_grand_mere", [])
    if astuces:
        st.markdown("#### 👵 Astuces de grand-mère")
        st.caption("Remèdes naturels et traditionnels, à utiliser avec modération.")
        for a in astuces:
            st.markdown(f"- {a}")

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
st.markdown(
    """
    <div class="hero">
      <h1>🌿 Plant Doctor</h1>
      <p>Photographiez votre plante — l'IA diagnostique sa santé et propose des solutions illustrées.</p>
    </div>
    """,
    unsafe_allow_html=True,
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
    st.caption("📱 Sur téléphone, la caméra **arrière** est utilisée. Sur ordinateur, la webcam.")
    photo = back_camera_input(height=360, width=340, key="cam")
    if photo is not None:
        image_bytes = photo.getvalue()
        st.image(image_bytes, caption="Photo capturée", use_container_width=True)
        if st.button("➕ Ajouter cette photo à l'analyse"):
            if ajouter_photo(image_bytes, detecter_media_type(image_bytes)):
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
            data = fichier.getvalue()
            if ajouter_photo(data, detecter_media_type(data)):
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
        st.session_state.pop("diagnostic", None)
        st.rerun()

    if lancer:
        client = anthropic.Anthropic(api_key=api_key)
        try:
            with st.spinner(f"Analyse de {len(photos)} photo(s) en cours… 🌱"):
                st.session_state["diagnostic"] = analyser_plante(
                    client, [(p["bytes"], p["media_type"]) for p in photos]
                )
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

# Affichage du dernier diagnostic (persistant entre les interactions)
diagnostic = st.session_state.get("diagnostic")
if diagnostic:
    st.divider()
    afficher_diagnostic(diagnostic)

    # Export PDF
    if diagnostic.get("est_une_plante", True):
        try:
            pdf_bytes = generer_pdf(diagnostic)
            nom = (diagnostic.get("plante") or "plante").lower().replace(" ", "_")
            nom = "".join(c for c in nom if c.isalnum() or c == "_") or "plante"
            st.download_button(
                "📄 Télécharger le diagnostic (PDF)",
                data=pdf_bytes,
                file_name=f"diagnostic_{nom}.pdf",
                mime="application/pdf",
            )
        except Exception as e:  # noqa: BLE001
            st.caption(f"(Export PDF indisponible : {e})")

# Pied de page — version
st.markdown(
    f"""
    <div style="text-align:center; margin-top:2.5rem; color:#7a9c83;
                font-size:.8rem; font-weight:600;">
      🌿 Plant Doctor · v{VERSION} — {VERSION_DATE} · propulsé par Claude
    </div>
    """,
    unsafe_allow_html=True,
)
