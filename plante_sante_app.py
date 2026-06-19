"""
🌿 Plant Doctor — Analyseur de santé des plantes
================================================

Application web optimisée pour smartphone : prenez une ou plusieurs photos d'une
plante (jusqu'à 4, sous différents angles), l'IA de vision de Claude analyse en
détail son état de santé, propose des solutions illustrées, et permet l'historique,
les rappels d'arrosage, l'export PDF et le choix de la langue.

Lancement local :
    streamlit run plante_sante_app.py

Clé API requise : ANTHROPIC_API_KEY (variable d'environnement ou .streamlit/secrets.toml).
"""

import base64
import hashlib
import io
import json
import os
import re
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timedelta

import anthropic
import streamlit as st
import streamlit.components.v1 as components
from streamlit_back_camera_input import back_camera_input

# Intégration facultative de la gestion des utilisateurs / quotas.
# Si ces modules sont absents (app lancée seule, sans authentification),
# Plant Doctor fonctionne normalement sans aucune restriction.
try:
    import auth as _auth
    import quotas as _quotas
    import database as _db
    _USER_MGMT = True
except Exception:
    _USER_MGMT = False


def _current_uid():
    """Identifiant de l'utilisateur connecté, ou None si pas d'authentification."""
    if not _USER_MGMT:
        return None
    user = _auth.get_current_user()
    return user["id"] if user else None


def _thumb_settings() -> tuple[int, int]:
    """Taille max / qualité des miniatures, configurables (THUMB_MAX_SIDE/QUALITY)."""
    max_side, quality = 600, 70
    if _USER_MGMT:
        try:
            max_side = int(_db.get_config("THUMB_MAX_SIDE") or max_side)
            quality = int(_db.get_config("THUMB_QUALITY") or quality)
        except (ValueError, TypeError):
            pass
    return max(200, min(2000, max_side)), max(30, min(95, quality))


def _corriger_orientation(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Applique l'orientation EXIF (photos de smartphone souvent tournées).

    Ne ré-encode que si une rotation est réellement nécessaire.
    """
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(image_bytes))
        orient = img.getexif().get(0x0112)  # balise Orientation EXIF
        if orient in (None, 1):
            return image_bytes, media_type  # déjà droite, rien à faire
        img = ImageOps.exif_transpose(img).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, media_type


def _thumbnail_bytes(image_bytes: bytes) -> bytes:
    """Réduit/compresse une image (orientation EXIF appliquée) -> octets JPEG."""
    from PIL import Image, ImageOps

    max_side, quality = _thumb_settings()
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _thumbnail_b64(image_bytes: bytes) -> str:
    """Miniature JPEG encodée en base64 (pour le stockage en base)."""
    return base64.b64encode(_thumbnail_bytes(image_bytes)).decode("ascii")


def _photos_pour_pdf() -> list[bytes]:
    """Octets des photos à inclure dans le PDF (revue d'historique ou photos courantes)."""
    thumbs = st.session_state.get("hist_thumbs")
    if thumbs:
        out = []
        for t in thumbs:
            try:
                out.append(base64.b64decode(t))
            except Exception:
                pass
        return out
    out = []
    for p in st.session_state.get("photos", []):
        try:
            out.append(_thumbnail_bytes(p["bytes"]))
        except Exception:
            pass
    return out


def _slug(s: str) -> str:
    s = (s or "plante").lower().replace(" ", "_")
    return "".join(c for c in s if c.isalnum() or c == "_") or "plante"


def _export_csv(uid: int) -> bytes:
    """Exporte l'historique de l'utilisateur en CSV (léger)."""
    import pandas as pd

    rows = _db.list_analyses(uid, limit=1000) or []
    if not rows:
        return b""
    df = pd.DataFrame(rows).rename(columns={"created_at": "date"})
    cols = [c for c in ["id", "date", "plante", "score"] if c in df.columns]
    return df[cols].to_csv(index=False).encode("utf-8")


def _export_zip_pdfs(uid: int) -> bytes:
    """Génère un ZIP contenant une fiche PDF par analyse de l'historique."""
    rows = _db.list_analyses(uid, limit=1000) or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in rows:
            full = _db.get_analysis(r["id"], uid)
            if not full:
                continue
            try:
                diag = json.loads(full["diagnostic"])
                imgs = []
                for t in json.loads(full.get("thumbnails") or "[]"):
                    try:
                        imgs.append(base64.b64decode(t))
                    except Exception:
                        pass
                pdf = generer_pdf(diag, imgs)
            except Exception:
                continue
            date = (r.get("created_at") or "")[:10]
            z.writestr(f"{date}_{_slug(r.get('plante'))}_{r['id']}.pdf", pdf)
    return buf.getvalue()

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="🌿 Plant Doctor",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed",
)

MODEL = "claude-opus-4-8"
MAX_PHOTOS = 4
MAX_HISTORIQUE = 12
VERSION = "1.8"
VERSION_DATE = "juin 2026"

LANGUES = {"Français": "fr", "English": "en", "Deutsch": "de"}
LANG_FULL = {"fr": "français", "en": "anglais (English)", "de": "allemand (Deutsch)"}

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap');
      html, body, [class*="css"] { font-family: 'Nunito', sans-serif; }
      .stApp { background: linear-gradient(180deg, #f4fbf5 0%, #ffffff 45%); overflow-x: hidden; }
      .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 760px; }
      .hero {
        background: linear-gradient(135deg, #15803d 0%, #22c55e 55%, #4ade80 100%);
        border-radius: 22px; padding: 1.6rem 1.4rem; color: #fff;
        box-shadow: 0 12px 30px rgba(22,163,74,.28); margin-bottom: 1.2rem;
      }
      .hero h1 { margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.5px; }
      .hero p { margin: .35rem 0 0; font-size: 1rem; opacity: .95; font-weight: 600; }
      .stButton button, .stDownloadButton button {
        width: 100%; border-radius: 14px; height: 3rem; font-size: 1.05rem; font-weight: 700;
        border: none; background: linear-gradient(135deg, #16a34a, #22c55e); color: #fff;
        transition: transform .08s ease, box-shadow .2s ease; box-shadow: 0 6px 16px rgba(22,163,74,.25);
      }
      .stButton button:hover, .stDownloadButton button:hover {
        transform: translateY(-1px); box-shadow: 0 10px 22px rgba(22,163,74,.35); color:#fff;
      }
      /* Bouton globe (déclencheur du popover de langue) : même style que les boutons */
      div[data-testid="stPopover"] > div > button,
      div[data-testid="stPopover"] button {
        background: linear-gradient(135deg, #16a34a, #22c55e) !important;
        color: #fff !important; border: none !important; border-radius: 14px !important;
        font-weight: 700 !important; font-size: 1.15rem !important;
        box-shadow: 0 6px 16px rgba(22,163,74,.25) !important;
      }
      div[data-testid="stPopover"] button:hover { filter: brightness(1.05); }
      div[data-testid="stMetric"] {
        background: #fff; border: 1px solid #d9efdd; border-radius: 16px;
        padding: .9rem .7rem; box-shadow: 0 4px 14px rgba(20,39,26,.05); text-align: center;
      }
      div[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 800; color: #15803d; }
      div[data-testid="stMetricLabel"] { justify-content: center; font-weight: 700; color:#436b4d; }
      .stProgress > div > div > div > div { background: linear-gradient(90deg, #f59e0b, #22c55e); }
      [data-testid="stExpander"] {
        border: 1px solid #d9efdd; border-radius: 16px; overflow: hidden;
        box-shadow: 0 4px 14px rgba(20,39,26,.05); background:#fff; margin-bottom:.5rem;
      }
      [data-testid="stExpander"] summary { font-weight: 700; }
      div[data-testid="stImage"] img { border-radius: 14px; }
      h4 { color: #15803d; font-weight: 800; margin-top: 1.3rem; }
      div[role="radiogroup"] label {
        background:#fff; border:1px solid #d9efdd; border-radius:999px;
        padding:.3rem .9rem; margin-right:.4rem; font-weight:700;
      }
      iframe, img, video, svg { max-width: 100% !important; }
      @media (max-width: 640px) {
        .block-container { padding-left: .8rem; padding-right: .8rem; }
        .hero { padding: 1.2rem 1rem; border-radius: 18px; }
        .hero h1 { font-size: 1.55rem; }
        .hero p { font-size: .9rem; }
        h4 { font-size: 1.05rem; }
        div[data-testid="stMetric"] { padding: .55rem .35rem; }
        div[data-testid="stMetricValue"] { font-size: 1.1rem; }
        div[data-testid="stMetricLabel"] p { font-size: .72rem; }
        div[data-testid="stHorizontalBlock"] { gap: .5rem; }
        .stButton button, .stDownloadButton button { font-size: 1rem; height: 2.8rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Traductions
# --------------------------------------------------------------------------- #
T = {
    "fr": {
        "hero_sub": "Photographiez votre plante — l'IA diagnostique sa santé et propose des solutions illustrées.",
        "add_hint": "**Ajoutez jusqu'à {n} photos** de la même plante (vue d'ensemble, feuilles, tiges, racines, zones abîmées…).",
        "src_cam": "📷 Appareil photo", "src_gallery": "🖼️ Depuis la galerie",
        "cam_caption": "📱 Sur téléphone, la caméra **arrière** est utilisée. Sur ordinateur, la webcam.",
        "add_photo_btn": "➕ Ajouter cette photo à l'analyse", "photo_added": "Photo ajoutée ✅",
        "photo_dup": "Photo déjà ajoutée ou maximum de {n} atteint.",
        "choose_photos": "Choisissez une ou plusieurs photos", "photos_added": "{n} photo(s) ajoutée(s) ✅",
        "selected": "**{n} / {max} photo(s) sélectionnée(s) :**", "remove": "🗑️ Retirer",
        "analyze": "🔬 Analyser la plante", "clear_all": "♻️ Tout effacer",
        "analyzing": "Analyse de {n} photo(s) en cours… 🌱",
        "add_one": "👆 Ajoutez au moins une photo pour démarrer l'analyse.",
        "err_auth": "Clé API invalide. Vérifiez votre `ANTHROPIC_API_KEY`.",
        "err_rate": "Trop de requêtes. Patientez quelques instants puis réessayez.",
        "err_api": "Erreur de l'API Claude : {e}",
        "err_parse": "La réponse de l'IA n'a pas pu être interprétée. Réessayez avec d'autres photos.",
        "no_plant": "🤔 Je n'ai pas reconnu de plante sur ces photos. Cadrez plus près du feuillage, avec une bonne lumière.",
        "dl_pdf": "📄 Télécharger le diagnostic (PDF)",
        "disclaimer": "⚠️ Diagnostic généré par une IA à titre indicatif. En cas de doute sur une plante de valeur, consultez un professionnel.",
        "footer": "🌿 Plant Doctor · v{v} — {d} · propulsé par Claude",
        "m_etat": "État général", "m_score": "Score de santé", "m_conf": "Confiance", "famille": "Famille",
        "sec_illus": "🖼️ Schéma illustré", "sec_ident": "🔬 Identification & analyse détaillée",
        "lbl_ident": "Identification :", "lbl_analyse": "Analyse :",
        "sec_cond": "🌡️ Conditions de culture", "sec_arros": "💧 Conseils d'arrosage",
        "f_freq": "Fréquence", "f_method": "Méthode", "f_manque": "Signes de manque d'eau", "f_exces": "Signes d'excès d'eau",
        "sec_lum": "☀️ Exposition à la lumière", "f_expo": "Exposition idéale", "f_empl": "Emplacement",
        "f_duree": "Durée / intensité", "f_eviter": "À éviter", "f_mauvais_ecl": "Signes d'un mauvais éclairage",
        "lbl_temp": "🌡️ Température / humidité :", "sec_eng": "🧪 Fertilisation / engrais",
        "f_type": "Type recommandé", "f_periode": "Période", "f_precaut": "Précautions",
        "sec_sub": "🪴 Substrats conseillés & déconseillés", "f_melange": "Mélange idéal",
        "f_conseilles": "Conseillés :", "f_aeviter2": "À éviter :",
        "sec_taille": "✂️ Taille & rempotage", "f_taille": "Taille", "f_rempotage": "Rempotage", "f_periode_ideale": "Période idéale",
        "sec_prob": "🔍 Problèmes détectés", "no_prob": "Aucun problème majeur détecté. Belle plante ! 🌟",
        "lbl_gravite": "Gravité", "lbl_sympt": "Symptômes :", "lbl_cause": "Cause probable :", "lbl_trait": "Traitement :",
        "see_examples": "📷 Voir des photos d'exemples de « {q} »",
        "sec_plan": "💊 Plan d'action prioritaire", "sec_prev": "🛡️ Conseils de prévention",
        "sec_routine": "🗓️ Routine d'entretien", "sec_astuces": "👵 Astuces de grand-mère",
        "astuces_cap": "Remèdes naturels et traditionnels, à utiliser avec modération.",
        "see_reference": "🌿 Voir des photos de référence de « {q} »",
        "sec_reminder": "🔔 Rappel d'arrosage",
        "reminder_hint": "Créez un rappel récurrent à ajouter au calendrier de votre téléphone.",
        "reminder_every": "Arroser tous les (jours) :", "dl_ics": "🔔 Télécharger le rappel (.ics)", "water_event": "💧 Arroser",
        "sec_hist": "📅 Historique des analyses", "hist_review": "Revoir", "hist_clear": "🗑️ Vider l'historique",
        "sec_photos": "📸 Photos analysées",
    },
    "en": {
        "hero_sub": "Photograph your plant — the AI diagnoses its health and suggests illustrated solutions.",
        "add_hint": "**Add up to {n} photos** of the same plant (whole view, leaves, stems, roots, damaged areas…).",
        "src_cam": "📷 Camera", "src_gallery": "🖼️ From gallery",
        "cam_caption": "📱 On phones the **rear** camera is used. On computers, the webcam.",
        "add_photo_btn": "➕ Add this photo to the analysis", "photo_added": "Photo added ✅",
        "photo_dup": "Photo already added or maximum of {n} reached.",
        "choose_photos": "Choose one or more photos", "photos_added": "{n} photo(s) added ✅",
        "selected": "**{n} / {max} photo(s) selected:**", "remove": "🗑️ Remove",
        "analyze": "🔬 Analyze the plant", "clear_all": "♻️ Clear all",
        "analyzing": "Analyzing {n} photo(s)… 🌱",
        "add_one": "👆 Add at least one photo to start the analysis.",
        "err_auth": "Invalid API key. Check your `ANTHROPIC_API_KEY`.",
        "err_rate": "Too many requests. Please wait a moment and try again.",
        "err_api": "Claude API error: {e}",
        "err_parse": "The AI response could not be parsed. Try again with other photos.",
        "no_plant": "🤔 I couldn't recognize a plant in these photos. Frame closer to the foliage, with good lighting.",
        "dl_pdf": "📄 Download the diagnosis (PDF)",
        "disclaimer": "⚠️ AI-generated diagnosis for guidance only. If in doubt about a valuable plant, consult a professional.",
        "footer": "🌿 Plant Doctor · v{v} — {d} · powered by Claude",
        "m_etat": "Overall state", "m_score": "Health score", "m_conf": "Confidence", "famille": "Family",
        "sec_illus": "🖼️ Illustrated diagram", "sec_ident": "🔬 Identification & detailed analysis",
        "lbl_ident": "Identification:", "lbl_analyse": "Analysis:",
        "sec_cond": "🌡️ Growing conditions", "sec_arros": "💧 Watering tips",
        "f_freq": "Frequency", "f_method": "Method", "f_manque": "Signs of under-watering", "f_exces": "Signs of over-watering",
        "sec_lum": "☀️ Light exposure", "f_expo": "Ideal exposure", "f_empl": "Placement",
        "f_duree": "Duration / intensity", "f_eviter": "Avoid", "f_mauvais_ecl": "Signs of poor lighting",
        "lbl_temp": "🌡️ Temperature / humidity:", "sec_eng": "🧪 Fertilization",
        "f_type": "Recommended type", "f_periode": "Period", "f_precaut": "Precautions",
        "sec_sub": "🪴 Recommended & discouraged substrates", "f_melange": "Ideal mix",
        "f_conseilles": "Recommended:", "f_aeviter2": "Avoid:",
        "sec_taille": "✂️ Pruning & repotting", "f_taille": "Pruning", "f_rempotage": "Repotting", "f_periode_ideale": "Ideal period",
        "sec_prob": "🔍 Detected problems", "no_prob": "No major problem detected. Nice plant! 🌟",
        "lbl_gravite": "Severity", "lbl_sympt": "Symptoms:", "lbl_cause": "Likely cause:", "lbl_trait": "Treatment:",
        "see_examples": "📷 See example photos of “{q}”",
        "sec_plan": "💊 Priority action plan", "sec_prev": "🛡️ Prevention tips",
        "sec_routine": "🗓️ Care routine", "sec_astuces": "👵 Grandma's tips",
        "astuces_cap": "Natural and traditional remedies, to use in moderation.",
        "see_reference": "🌿 See reference photos of “{q}”",
        "sec_reminder": "🔔 Watering reminder",
        "reminder_hint": "Create a recurring reminder to add to your phone's calendar.",
        "reminder_every": "Water every (days):", "dl_ics": "🔔 Download the reminder (.ics)", "water_event": "💧 Water",
        "sec_hist": "📅 Analysis history", "hist_review": "View again", "hist_clear": "🗑️ Clear history",
        "sec_photos": "📸 Analyzed photos",
    },
    "de": {
        "hero_sub": "Fotografieren Sie Ihre Pflanze — die KI diagnostiziert ihre Gesundheit und schlägt illustrierte Lösungen vor.",
        "add_hint": "**Fügen Sie bis zu {n} Fotos** derselben Pflanze hinzu (Gesamtansicht, Blätter, Stängel, Wurzeln, beschädigte Stellen…).",
        "src_cam": "📷 Kamera", "src_gallery": "🖼️ Aus der Galerie",
        "cam_caption": "📱 Auf dem Handy wird die **Rückkamera** verwendet. Am Computer die Webcam.",
        "add_photo_btn": "➕ Dieses Foto zur Analyse hinzufügen", "photo_added": "Foto hinzugefügt ✅",
        "photo_dup": "Foto bereits hinzugefügt oder Maximum von {n} erreicht.",
        "choose_photos": "Wählen Sie ein oder mehrere Fotos", "photos_added": "{n} Foto(s) hinzugefügt ✅",
        "selected": "**{n} / {max} Foto(s) ausgewählt:**", "remove": "🗑️ Entfernen",
        "analyze": "🔬 Pflanze analysieren", "clear_all": "♻️ Alles löschen",
        "analyzing": "Analysiere {n} Foto(s)… 🌱",
        "add_one": "👆 Fügen Sie mindestens ein Foto hinzu, um die Analyse zu starten.",
        "err_auth": "Ungültiger API-Schlüssel. Prüfen Sie `ANTHROPIC_API_KEY`.",
        "err_rate": "Zu viele Anfragen. Bitte warten Sie kurz und versuchen Sie es erneut.",
        "err_api": "Claude-API-Fehler: {e}",
        "err_parse": "Die KI-Antwort konnte nicht verarbeitet werden. Versuchen Sie es mit anderen Fotos.",
        "no_plant": "🤔 Auf diesen Fotos konnte ich keine Pflanze erkennen. Fotografieren Sie näher am Laub, bei gutem Licht.",
        "dl_pdf": "📄 Diagnose herunterladen (PDF)",
        "disclaimer": "⚠️ KI-generierte Diagnose, nur als Orientierung. Im Zweifel bei wertvollen Pflanzen einen Fachmann fragen.",
        "footer": "🌿 Plant Doctor · v{v} — {d} · powered by Claude",
        "m_etat": "Allgemeinzustand", "m_score": "Gesundheitswert", "m_conf": "Sicherheit", "famille": "Familie",
        "sec_illus": "🖼️ Illustriertes Schema", "sec_ident": "🔬 Identifikation & detaillierte Analyse",
        "lbl_ident": "Identifikation:", "lbl_analyse": "Analyse:",
        "sec_cond": "🌡️ Kulturbedingungen", "sec_arros": "💧 Gießtipps",
        "f_freq": "Häufigkeit", "f_method": "Methode", "f_manque": "Anzeichen von Wassermangel", "f_exces": "Anzeichen von Überwässerung",
        "sec_lum": "☀️ Lichtexposition", "f_expo": "Ideale Exposition", "f_empl": "Standort",
        "f_duree": "Dauer / Intensität", "f_eviter": "Vermeiden", "f_mauvais_ecl": "Anzeichen schlechter Beleuchtung",
        "lbl_temp": "🌡️ Temperatur / Luftfeuchtigkeit:", "sec_eng": "🧪 Düngung",
        "f_type": "Empfohlener Typ", "f_periode": "Zeitraum", "f_precaut": "Vorsichtsmaßnahmen",
        "sec_sub": "🪴 Empfohlene & ungeeignete Substrate", "f_melange": "Ideale Mischung",
        "f_conseilles": "Empfohlen:", "f_aeviter2": "Vermeiden:",
        "sec_taille": "✂️ Schnitt & Umtopfen", "f_taille": "Schnitt", "f_rempotage": "Umtopfen", "f_periode_ideale": "Idealer Zeitraum",
        "sec_prob": "🔍 Erkannte Probleme", "no_prob": "Kein größeres Problem erkannt. Schöne Pflanze! 🌟",
        "lbl_gravite": "Schweregrad", "lbl_sympt": "Symptome:", "lbl_cause": "Wahrscheinliche Ursache:", "lbl_trait": "Behandlung:",
        "see_examples": "📷 Beispielfotos von „{q}“ ansehen",
        "sec_plan": "💊 Prioritärer Maßnahmenplan", "sec_prev": "🛡️ Vorbeugungstipps",
        "sec_routine": "🗓️ Pflegeroutine", "sec_astuces": "👵 Großmutters Tipps",
        "astuces_cap": "Natürliche und traditionelle Mittel, in Maßen anwenden.",
        "see_reference": "🌿 Referenzfotos von „{q}“ ansehen",
        "sec_reminder": "🔔 Gießerinnerung",
        "reminder_hint": "Erstellen Sie eine wiederkehrende Erinnerung für den Kalender Ihres Telefons.",
        "reminder_every": "Gießen alle (Tage):", "dl_ics": "🔔 Erinnerung herunterladen (.ics)", "water_event": "💧 Gießen",
        "sec_hist": "📅 Analyseverlauf", "hist_review": "Erneut ansehen", "hist_clear": "🗑️ Verlauf löschen",
        "sec_photos": "📸 Analysierte Fotos",
    },
}


def tr(key, **kw):
    lang = st.session_state.get("lang", "fr")
    s = T.get(lang, T["fr"]).get(key) or T["fr"].get(key, key)
    return s.format(**kw) if kw else s


# --------------------------------------------------------------------------- #
# Clé API
# --------------------------------------------------------------------------- #
def get_api_key():
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


# --------------------------------------------------------------------------- #
# Schéma de sortie structurée
# --------------------------------------------------------------------------- #
SCHEMA = {
    "type": "object",
    "properties": {
        "est_une_plante": {"type": "boolean"},
        "plante": {"type": "string"},
        "nom_latin": {"type": "string"},
        "famille": {"type": "string"},
        "etat_general": {"type": "string", "enum": ["Bon", "Moyen", "Mauvais", "Inconnu"]},
        "score_sante": {"type": "integer", "description": "0 (mourante) à 100 (parfaite santé)."},
        "resume": {"type": "string"},
        "identification_details": {"type": "string"},
        "analyse_detaillee": {"type": "string"},
        "conditions_culture": {
            "type": "object",
            "properties": {
                "arrosage": {
                    "type": "object",
                    "properties": {
                        "frequence": {"type": "string"},
                        "methode": {"type": "string"},
                        "signes_de_manque": {"type": "string"},
                        "signes_d_exces": {"type": "string"},
                    },
                    "required": ["frequence", "methode", "signes_de_manque", "signes_d_exces"],
                    "additionalProperties": False,
                },
                "lumiere": {
                    "type": "object",
                    "properties": {
                        "exposition": {"type": "string"},
                        "emplacement": {"type": "string"},
                        "duree": {"type": "string"},
                        "a_eviter": {"type": "string"},
                        "signes_mauvais_eclairage": {"type": "string"},
                    },
                    "required": ["exposition", "emplacement", "duree", "a_eviter", "signes_mauvais_eclairage"],
                    "additionalProperties": False,
                },
                "temperature_humidite": {"type": "string"},
                "engrais": {
                    "type": "object",
                    "properties": {
                        "type_recommande": {"type": "string"},
                        "frequence": {"type": "string"},
                        "periode": {"type": "string"},
                        "precautions": {"type": "string"},
                    },
                    "required": ["type_recommande", "frequence", "periode", "precautions"],
                    "additionalProperties": False,
                },
                "substrat": {
                    "type": "object",
                    "properties": {
                        "melange_ideal": {"type": "string"},
                        "conseilles": {"type": "array", "items": {"type": "string"}},
                        "deconseilles": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["melange_ideal", "conseilles", "deconseilles"],
                    "additionalProperties": False,
                },
                "taille_rempotage": {
                    "type": "object",
                    "properties": {
                        "taille": {"type": "string", "description": "Conseils de taille (quand et comment)."},
                        "rempotage": {"type": "string", "description": "Conseils de rempotage (fréquence, quand, comment)."},
                        "periode_ideale": {"type": "string", "description": "Période idéale pour tailler/rempoter."},
                    },
                    "required": ["taille", "rempotage", "periode_ideale"],
                    "additionalProperties": False,
                },
            },
            "required": ["arrosage", "lumiere", "temperature_humidite", "engrais", "substrat", "taille_rempotage"],
            "additionalProperties": False,
        },
        "problemes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "symptomes": {"type": "string"},
                    "cause": {"type": "string"},
                    "gravite": {"type": "string", "enum": ["Faible", "Modérée", "Élevée"]},
                    "traitement": {"type": "array", "items": {"type": "string"}},
                    "terme_recherche_image": {"type": "string"},
                },
                "required": ["nom", "symptomes", "cause", "gravite", "traitement", "terme_recherche_image"],
                "additionalProperties": False,
            },
        },
        "solutions": {"type": "array", "items": {"type": "string"}},
        "prevention": {"type": "array", "items": {"type": "string"}},
        "calendrier_entretien": {"type": "array", "items": {"type": "string"}},
        "astuces_grand_mere": {"type": "array", "items": {"type": "string"}},
        "intervalle_arrosage_jours": {
            "type": "integer",
            "description": "Intervalle moyen recommandé entre deux arrosages, en jours.",
        },
        "illustration_svg": {
            "type": "string",
            "description": "Dessin SVG simple (viewBox ~400x360) localisant les zones atteintes, sans script. Vide si non pertinent.",
        },
        "confiance": {"type": "string", "enum": ["Faible", "Moyenne", "Élevée"]},
    },
    "required": [
        "est_une_plante", "plante", "nom_latin", "famille", "etat_general", "score_sante",
        "resume", "identification_details", "analyse_detaillee", "conditions_culture",
        "problemes", "solutions", "prevention", "calendrier_entretien", "astuces_grand_mere",
        "intervalle_arrosage_jours", "illustration_svg", "confiance",
    ],
    "additionalProperties": False,
}


def build_system_prompt(lang: str) -> str:
    return (
        "Tu es un expert en phytopathologie et en horticulture. À partir d'UNE OU PLUSIEURS photos "
        "de la MÊME plante, tu réalises un diagnostic détaillé : identification, état de santé, "
        "maladies, parasites, carences, stress. Tu proposes des solutions concrètes, des conseils "
        "d'arrosage, d'exposition à la lumière, de fertilisation, de substrats, de taille et de "
        "rempotage, ainsi que des astuces naturelles traditionnelles ('de grand-mère'). "
        "Sois précis, pédagogique et bienveillant. "
        f"Tu rédiges TOUTES les valeurs textuelles du JSON en {LANG_FULL.get(lang, 'français')}. "
        "Si les images ne contiennent pas de plante, indique-le via 'est_une_plante'. "
        "Base ton diagnostic uniquement sur ce qui est visible ; ajuste ta confiance selon la "
        "netteté, le cadrage et le nombre de photos."
    )


MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def detecter_media_type(b: bytes) -> str:
    if b[:8].startswith(b"\x89PNG"):
        return "image/png"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def analyser_plante(client, photos, lang):
    content = []
    for image_bytes, media_type in photos:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.standard_b64encode(image_bytes).decode("utf-8")},
        })
    content.append({
        "type": "text",
        "text": f"Voici {len(photos)} photo(s) de la même plante. Analyse en détail et suis strictement le format JSON.",
    })
    response = client.messages.create(
        model=MODEL, max_tokens=5500,
        system=build_system_prompt(lang),
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "{}")
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
COULEUR_ETAT = {"Bon": "🟢", "Moyen": "🟡", "Mauvais": "🔴", "Inconnu": "⚪"}
COULEUR_GRAVITE = {"Faible": "🟢", "Modérée": "🟡", "Élevée": "🔴"}

_PDF_REMP = {"œ": "oe", "Œ": "OE", "æ": "ae", "—": "-", "–": "-", "’": "'", "‘": "'",
             "“": '"', "”": '"', "„": '"', "…": "...", "•": "-", "→": "->", "≈": "~"}


def _pdf_txt(s) -> str:
    s = str(s)
    for k, v in _PDF_REMP.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "ignore").decode("latin-1").strip()


def lien_images(terme: str) -> str:
    return f"https://www.google.com/search?tbm=isch&q={urllib.parse.quote_plus(terme)}"


def extraire_jours(diag) -> int:
    """Détermine l'intervalle d'arrosage en jours (1-60)."""
    val = diag.get("intervalle_arrosage_jours")
    if isinstance(val, int) and val > 0:
        return max(1, min(60, val))
    freq = (diag.get("conditions_culture", {}).get("arrosage", {}) or {}).get("frequence", "")
    m = re.search(r"(\d+)", str(freq))
    return max(1, min(60, int(m.group(1)))) if m else 7


def generer_ics(plante: str, jours: int) -> bytes:
    now = datetime.now()
    start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if start < now:
        start += timedelta(days=1)
    dtstart = start.strftime("%Y%m%dT%H%M%S")
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    summary = f"{tr('water_event')} {plante}".strip()
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Plant Doctor//FR", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT", f"UID:{uuid.uuid4()}@plant-doctor", f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}", "DURATION:PT15M", f"RRULE:FREQ=DAILY;INTERVAL={jours}",
        f"SUMMARY:{summary}", f"DESCRIPTION:Plant Doctor - {summary}",
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{summary}", "TRIGGER:PT0S", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def generer_pdf(diag: dict, photos: list = None) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from PIL import Image

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    vert = (21, 128, 61)

    def _line(txt, h):
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, h, _pdf_txt(txt), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def titre(txt, size=13):
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

    def grille_photos(images):
        """Insère les photos analysées en grille (2 colonnes)."""
        titre(tr("sec_photos"))
        col_w, gap = 85, 10
        x0 = pdf.l_margin
        y = pdf.get_y()
        max_h = 0
        for i, b in enumerate(images[:4]):
            col = i % 2
            if col == 0 and i > 0:
                y += max_h + 4
                max_h = 0
            try:
                im = Image.open(io.BytesIO(b))
                w0, h0 = im.size
                h = col_w * h0 / w0
                pdf.image(io.BytesIO(b), x=x0 + col * (col_w + gap), y=y, w=col_w, h=h)
                max_h = max(max_h, h)
            except Exception:
                continue
        pdf.set_y(y + max_h + 6)

    titre("Plant Doctor - Diagnostic", 18)
    sous = diag.get("plante", "Plante")
    if diag.get("nom_latin"):
        sous += f" ({diag['nom_latin']})"
    para(sous, bold=True, size=13)
    if diag.get("famille"):
        para(f"{tr('famille')} : {diag['famille']}")
    para(f"{tr('m_etat')} : {diag.get('etat_general', '-')}   |   "
         f"{tr('m_score')} : {diag.get('score_sante', 0)}/100   |   "
         f"{tr('m_conf')} : {diag.get('confiance', '-')}")
    if diag.get("resume"):
        para(diag["resume"])
    pdf.ln(2)

    if photos:
        grille_photos(photos)

    if diag.get("identification_details"):
        titre(tr("sec_ident")); para(diag["identification_details"])
    if diag.get("analyse_detaillee"):
        para(diag["analyse_detaillee"])

    cc = diag.get("conditions_culture", {})
    if cc:
        titre(tr("sec_cond"))
        arr = cc.get("arrosage", {})
        if isinstance(arr, dict) and any(arr.values()):
            para(tr("sec_arros"), bold=True)
            for k, lbl in [("frequence", "f_freq"), ("methode", "f_method"),
                           ("signes_de_manque", "f_manque"), ("signes_d_exces", "f_exces")]:
                if arr.get(k):
                    puce(f"{tr(lbl)} : {arr[k]}")
        lum = cc.get("lumiere", {})
        if isinstance(lum, dict) and any(lum.values()):
            para(tr("sec_lum"), bold=True)
            for k, lbl in [("exposition", "f_expo"), ("emplacement", "f_empl"), ("duree", "f_duree"),
                           ("a_eviter", "f_eviter"), ("signes_mauvais_eclairage", "f_mauvais_ecl")]:
                if lum.get(k):
                    puce(f"{tr(lbl)} : {lum[k]}")
        if cc.get("temperature_humidite"):
            para(tr("lbl_temp"), bold=True); puce(cc["temperature_humidite"])
        eng = cc.get("engrais", {})
        if isinstance(eng, dict) and any(eng.values()):
            para(tr("sec_eng"), bold=True)
            for k, lbl in [("type_recommande", "f_type"), ("frequence", "f_freq"),
                           ("periode", "f_periode"), ("precautions", "f_precaut")]:
                if eng.get(k):
                    puce(f"{tr(lbl)} : {eng[k]}")
        sub = cc.get("substrat", {})
        if isinstance(sub, dict) and any(sub.values()):
            para(tr("sec_sub"), bold=True)
            if sub.get("melange_ideal"):
                puce(f"{tr('f_melange')} : {sub['melange_ideal']}")
            for s in sub.get("conseilles", []):
                puce(f"+ {s}")
            for s in sub.get("deconseilles", []):
                puce(f"- {s}")
        ta = cc.get("taille_rempotage", {})
        if isinstance(ta, dict) and any(ta.values()):
            para(tr("sec_taille"), bold=True)
            for k, lbl in [("taille", "f_taille"), ("rempotage", "f_rempotage"), ("periode_ideale", "f_periode_ideale")]:
                if ta.get(k):
                    puce(f"{tr(lbl)} : {ta[k]}")

    problemes = diag.get("problemes", [])
    if problemes:
        titre(tr("sec_prob"))
        for p in problemes:
            para(f"{p.get('nom', '-')} ({tr('lbl_gravite')} : {p.get('gravite', '-')})", bold=True)
            if p.get("symptomes"):
                puce(f"{tr('lbl_sympt')} {p['symptomes']}")
            if p.get("cause"):
                puce(f"{tr('lbl_cause')} {p['cause']}")
            for t in p.get("traitement", []):
                puce(f"{tr('lbl_trait')} {t}")

    for cle, sec in [("solutions", "sec_plan"), ("prevention", "sec_prev"),
                     ("calendrier_entretien", "sec_routine"), ("astuces_grand_mere", "sec_astuces")]:
        items = diag.get(cle, [])
        if items:
            titre(tr(sec))
            for it in items:
                puce(it)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    _line(f"Plant Doctor v{VERSION}", 5)
    return bytes(pdf.output())


# --------------------------------------------------------------------------- #
# Affichage du diagnostic
# --------------------------------------------------------------------------- #
def afficher_diagnostic(diag: dict) -> None:
    if not diag.get("est_une_plante", True):
        st.warning(tr("no_plant"))
        return

    plante = diag.get("plante", "Plante")
    nom_latin = diag.get("nom_latin", "")
    titre = f"🪴 {plante}"
    if nom_latin:
        titre += f"  ·  *{nom_latin}*"
    st.markdown(f"### {titre}")
    if diag.get("famille"):
        st.caption(f"{tr('famille')} : {diag['famille']}")
    if diag.get("resume"):
        st.write(diag["resume"])

    c1, c2, c3 = st.columns(3)
    etat = diag.get("etat_general", "Inconnu")
    c1.metric(tr("m_etat"), f"{COULEUR_ETAT.get(etat, '⚪')} {etat}")
    score = int(diag.get("score_sante", 0))
    c2.metric(tr("m_score"), f"{score}/100")
    c3.metric(tr("m_conf"), diag.get("confiance", "—"))
    st.progress(max(0, min(100, score)) / 100)

    svg = diag.get("illustration_svg", "").strip()
    if svg.startswith("<svg"):
        st.markdown(f"#### {tr('sec_illus')}")
        components.html(
            "<div style='display:flex;justify-content:center;width:100%;'>"
            "<style>svg{width:100%;height:auto;max-width:360px;}</style>" + svg + "</div>",
            height=340,
        )

    if diag.get("identification_details") or diag.get("analyse_detaillee"):
        with st.expander(tr("sec_ident"), expanded=True):
            if diag.get("identification_details"):
                st.markdown(f"**{tr('lbl_ident')}**")
                st.write(diag["identification_details"])
            if diag.get("analyse_detaillee"):
                st.markdown(f"**{tr('lbl_analyse')}**")
                st.write(diag["analyse_detaillee"])

    cc = diag.get("conditions_culture", {})
    if cc:
        st.markdown(f"#### {tr('sec_cond')}")
        arr = cc.get("arrosage", {})
        if isinstance(arr, dict) and any(arr.values()):
            with st.expander(tr("sec_arros"), expanded=True):
                for k, lbl in [("frequence", "f_freq"), ("methode", "f_method"),
                               ("signes_de_manque", "f_manque"), ("signes_d_exces", "f_exces")]:
                    if arr.get(k):
                        st.markdown(f"**{tr(lbl)} :** {arr[k]}")
        lum = cc.get("lumiere", {})
        if isinstance(lum, dict) and any(lum.values()):
            with st.expander(tr("sec_lum"), expanded=True):
                for k, lbl in [("exposition", "f_expo"), ("emplacement", "f_empl"), ("duree", "f_duree"),
                               ("a_eviter", "f_eviter"), ("signes_mauvais_eclairage", "f_mauvais_ecl")]:
                    if lum.get(k):
                        st.markdown(f"**{tr(lbl)} :** {lum[k]}")
        if cc.get("temperature_humidite"):
            st.markdown(f"{tr('lbl_temp')} {cc['temperature_humidite']}")
        eng = cc.get("engrais", {})
        if isinstance(eng, dict) and any(eng.values()):
            with st.expander(tr("sec_eng"), expanded=True):
                for k, lbl in [("type_recommande", "f_type"), ("frequence", "f_freq"),
                               ("periode", "f_periode"), ("precautions", "f_precaut")]:
                    if eng.get(k):
                        st.markdown(f"**{tr(lbl)} :** {eng[k]}")
        sub = cc.get("substrat", {})
        if isinstance(sub, dict) and any(sub.values()):
            with st.expander(tr("sec_sub"), expanded=True):
                if sub.get("melange_ideal"):
                    st.markdown(f"🌱 **{tr('f_melange')} :** {sub['melange_ideal']}")
                if sub.get("conseilles"):
                    st.markdown(f"✅ **{tr('f_conseilles')}**")
                    for s in sub["conseilles"]:
                        st.markdown(f"- {s}")
                if sub.get("deconseilles"):
                    st.markdown(f"🚫 **{tr('f_aeviter2')}**")
                    for s in sub["deconseilles"]:
                        st.markdown(f"- {s}")
        ta = cc.get("taille_rempotage", {})
        if isinstance(ta, dict) and any(ta.values()):
            with st.expander(tr("sec_taille"), expanded=True):
                for k, lbl in [("taille", "f_taille"), ("rempotage", "f_rempotage"), ("periode_ideale", "f_periode_ideale")]:
                    if ta.get(k):
                        st.markdown(f"**{tr(lbl)} :** {ta[k]}")

    problemes = diag.get("problemes", [])
    st.markdown(f"#### {tr('sec_prob')}")
    if not problemes:
        st.success(tr("no_prob"))
    else:
        for p in problemes:
            icone = COULEUR_GRAVITE.get(p.get("gravite", ""), "⚪")
            with st.expander(f"{icone} {p.get('nom', '-')}  ·  {tr('lbl_gravite')} : {p.get('gravite', '—')}"):
                if p.get("symptomes"):
                    st.markdown(f"**{tr('lbl_sympt')}** {p['symptomes']}")
                if p.get("cause"):
                    st.markdown(f"**{tr('lbl_cause')}** {p['cause']}")
                if p.get("traitement"):
                    st.markdown(f"**{tr('lbl_trait')}**")
                    for t in p["traitement"]:
                        st.markdown(f"- {t}")
                terme = p.get("terme_recherche_image") or p.get("nom", "")
                if terme:
                    st.markdown(f"[{tr('see_examples', q=terme)}]({lien_images(terme)})")

    if diag.get("solutions"):
        st.markdown(f"#### {tr('sec_plan')}")
        for i, s in enumerate(diag["solutions"], 1):
            st.markdown(f"**{i}.** {s}")
    if diag.get("prevention"):
        st.markdown(f"#### {tr('sec_prev')}")
        for c in diag["prevention"]:
            st.markdown(f"- {c}")
    if diag.get("calendrier_entretien"):
        st.markdown(f"#### {tr('sec_routine')}")
        for c in diag["calendrier_entretien"]:
            st.markdown(f"- {c}")
    if diag.get("astuces_grand_mere"):
        st.markdown(f"#### {tr('sec_astuces')}")
        st.caption(tr("astuces_cap"))
        for a in diag["astuces_grand_mere"]:
            st.markdown(f"- {a}")

    terme_plante = " ".join(x for x in [plante, nom_latin] if x).strip()
    if terme_plante:
        st.markdown(f"[{tr('see_reference', q=terme_plante)}]({lien_images(terme_plante)})")

    st.caption(tr("disclaimer"))


def _empreinte(image_bytes: bytes) -> str:
    return hashlib.md5(image_bytes).hexdigest()


def ajouter_photo(image_bytes: bytes, media_type: str) -> bool:
    # Corrige l'orientation EXIF avant tout stockage / analyse / affichage
    image_bytes, media_type = _corriger_orientation(image_bytes, media_type)
    photos = st.session_state.setdefault("photos", [])
    empreinte = _empreinte(image_bytes)
    if any(p["id"] == empreinte for p in photos):
        return False
    if len(photos) >= MAX_PHOTOS:
        return False
    photos.append({"id": empreinte, "bytes": image_bytes, "media_type": media_type})
    return True


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
# Sélecteur de langue : bouton 🌐 (globe) ouvrant un menu (popover)
DRAPEAUX = {"fr": "🇫🇷", "en": "🇬🇧", "de": "🇩🇪"}
st.session_state.setdefault("lang", "fr")
_, col_globe = st.columns([5, 1])
with col_globe:
    with st.popover(f"🌐 {DRAPEAUX.get(st.session_state['lang'], '')}", use_container_width=True):
        st.caption("🌍 Langue / Language / Sprache")
        for nom, code in LANGUES.items():
            actif = "✅ " if code == st.session_state["lang"] else ""
            drapeau = DRAPEAUX.get(code, "")
            if st.button(f"{actif}{drapeau} {nom}", key=f"setlang_{code}", use_container_width=True):
                st.session_state["lang"] = code
                st.rerun()

st.markdown(
    f"""<div class="hero"><h1>🌿 Plant Doctor</h1><p>{tr('hero_sub')}</p></div>""",
    unsafe_allow_html=True,
)

api_key = get_api_key()
if not api_key:
    st.error(
        "🔑 Aucune clé API Anthropic configurée.\n\n"
        "Définissez `ANTHROPIC_API_KEY` ou créez `.streamlit/secrets.toml` :\n\n"
        "```toml\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```"
    )
    st.stop()

st.session_state.setdefault("photos", [])
st.session_state.setdefault("historique", [])

# Historique : persistant en base si connecté, sinon par session
_hist_uid = _current_uid()
if _hist_uid is not None:
    # Historique PERSISTANT (base de données) — survit aux reconnexions
    entrees = _db.list_analyses(_hist_uid, limit=50)
    if entrees:
        with st.expander(f"{tr('sec_hist')} ({len(entrees)})"):
            for e in entrees:
                date_aff = (e.get("created_at") or "")[:16].replace("T", " ")
                cols = st.columns([1, 3.4, 1.2, 0.7], vertical_alignment="center")
                # Vignette (première photo de l'analyse)
                vignette = None
                try:
                    arr = json.loads(e.get("thumbnails") or "[]")
                    if arr:
                        vignette = base64.b64decode(arr[0])
                except Exception:
                    pass
                if vignette:
                    cols[0].image(vignette, use_container_width=True)
                else:
                    cols[0].markdown("🪴")
                cols[1].markdown(f"**{date_aff}**  \n{e['plante']} · {e['score']}/100")
                if cols[2].button(tr("hist_review"), key=f"hist_{e['id']}"):
                    full = _db.get_analysis(e["id"], _hist_uid)
                    if full:
                        st.session_state["diagnostic"] = json.loads(full["diagnostic"])
                        st.session_state["hist_thumbs"] = json.loads(full.get("thumbnails") or "[]")
                    st.rerun()
                if cols[3].button("🗑️", key=f"histdel_{e['id']}"):
                    _db.delete_analysis(e["id"], _hist_uid)
                    st.rerun()

            st.divider()
            # Actions d'export / nettoyage — en ligne
            b1, b2, b3 = st.columns(3)
            b1.download_button(
                "📥 CSV", data=_export_csv(_hist_uid),
                file_name="historique_analyses.csv", mime="text/csv", key="exp_csv",
            )
            if b2.button("📦 PDF (ZIP)", key="prep_zip"):
                with st.spinner("Génération des PDF…"):
                    st.session_state["zip_export"] = _export_zip_pdfs(_hist_uid)
            if b3.button(tr("hist_clear"), key="hist_clear_db"):
                _db.delete_all_analyses(_hist_uid)
                st.session_state.pop("zip_export", None)
                st.rerun()
            if st.session_state.get("zip_export"):
                st.download_button(
                    "⬇️ Télécharger le ZIP des fiches PDF",
                    data=st.session_state["zip_export"],
                    file_name="analyses_pdf.zip", mime="application/zip", key="dl_zip",
                )
elif st.session_state["historique"]:
    # Historique de session (app utilisée sans authentification)
    with st.expander(f"{tr('sec_hist')} ({len(st.session_state['historique'])})"):
        for entree in reversed(st.session_state["historique"]):
            cols = st.columns([4, 1])
            cols[0].markdown(
                f"**{entree['date']}** · {entree['plante']} · {entree['score']}/100"
            )
            if cols[1].button(tr("hist_review"), key=f"hist_{entree['id']}"):
                st.session_state["diagnostic"] = entree["diag"]
                st.rerun()
        if st.button(tr("hist_clear")):
            st.session_state["historique"] = []
            st.rerun()

st.markdown(tr("add_hint", n=MAX_PHOTOS))

source = st.radio("src", [tr("src_cam"), tr("src_gallery")], horizontal=True, label_visibility="collapsed")

if source == tr("src_cam"):
    st.caption(tr("cam_caption"))
    photo = back_camera_input(height=360, width=340, key="cam")
    if photo is not None:
        image_bytes = photo.getvalue()
        st.image(image_bytes, use_container_width=True)
        if st.button(tr("add_photo_btn")):
            if ajouter_photo(image_bytes, detecter_media_type(image_bytes)):
                st.success(tr("photo_added"))
            else:
                st.info(tr("photo_dup", n=MAX_PHOTOS))
else:
    fichiers = st.file_uploader(tr("choose_photos"), type=list(MEDIA_TYPES.keys()), accept_multiple_files=True)
    if fichiers:
        ajoutees = 0
        for fichier in fichiers:
            data = fichier.getvalue()
            if ajouter_photo(data, detecter_media_type(data)):
                ajoutees += 1
        if ajoutees:
            st.success(tr("photos_added", n=ajoutees))

photos = st.session_state.get("photos", [])
if photos:
    st.markdown(tr("selected", n=len(photos), max=MAX_PHOTOS))
    cols = st.columns(min(len(photos), 4))
    for i, p in enumerate(photos):
        with cols[i % len(cols)]:
            st.image(p["bytes"], use_container_width=True)
            if st.button(tr("remove"), key=f"del_{p['id']}"):
                st.session_state["photos"] = [x for x in photos if x["id"] != p["id"]]
                st.rerun()

    # Quota d'analyses restant (si authentification active)
    uid = _current_uid()
    if uid is not None:
        cap = _quotas.quota_caption(uid)
        if cap:
            st.caption(cap)

    col_a, col_b = st.columns(2)
    lancer = col_a.button(tr("analyze"), type="primary")
    if col_b.button(tr("clear_all")):
        st.session_state["photos"] = []
        st.session_state.pop("diagnostic", None)
        st.rerun()

    if lancer:
        # Vérification du quota avant toute consommation de l'API
        if uid is not None:
            autorise, msg_quota, _ = _quotas.check_quota(uid)
            if not autorise:
                st.error("⛔ " + msg_quota)
                st.stop()

        client = anthropic.Anthropic(api_key=api_key)
        try:
            with st.spinner(tr("analyzing", n=len(photos))):
                diag = analyser_plante(
                    client, [(p["bytes"], p["media_type"]) for p in photos], st.session_state["lang"]
                )
            st.session_state["diagnostic"] = diag
            st.session_state.pop("hist_thumbs", None)  # nouvelles photos courantes
            if uid is not None:
                _quotas.record_analysis(uid)  # comptabilise l'analyse effectuée
            if diag.get("est_une_plante", True):
                if uid is not None:
                    # Sauvegarde PERSISTANTE en base (miniatures réduites + diagnostic)
                    try:
                        thumbs = [_thumbnail_b64(p["bytes"]) for p in photos]
                    except Exception:
                        thumbs = []
                    _db.save_analysis(
                        uid, diag.get("plante", "—"), int(diag.get("score_sante", 0)),
                        json.dumps(diag), json.dumps(thumbs),
                    )
                    # Purge automatique des analyses trop anciennes (rétention)
                    cutoff = _db.retention_cutoff_iso()
                    if cutoff:
                        _db.delete_analyses_before(cutoff)
                else:
                    # Historique de session (sans authentification)
                    st.session_state["historique"].append({
                        "id": uuid.uuid4().hex,
                        "date": datetime.now().strftime("%d/%m %H:%M"),
                        "plante": diag.get("plante", "—"),
                        "score": int(diag.get("score_sante", 0)),
                        "diag": diag,
                    })
                    st.session_state["historique"] = st.session_state["historique"][-MAX_HISTORIQUE:]
        except anthropic.AuthenticationError:
            st.error(tr("err_auth"))
        except anthropic.RateLimitError:
            st.error(tr("err_rate"))
        except anthropic.APIError as e:
            st.error(tr("err_api", e=e))
        except (json.JSONDecodeError, KeyError):
            st.error(tr("err_parse"))
else:
    st.info(tr("add_one"))

# Diagnostic courant (persistant)
diagnostic = st.session_state.get("diagnostic")
if diagnostic:
    st.divider()

    # Photos stockées (lorsqu'on revoit une analyse de l'historique)
    _thumbs = st.session_state.get("hist_thumbs")
    if _thumbs:
        st.markdown(f"**{tr('sec_photos')}**")
        tcols = st.columns(min(len(_thumbs), 4))
        for i, b64 in enumerate(_thumbs):
            try:
                tcols[i % len(tcols)].image(base64.b64decode(b64), use_container_width=True)
            except Exception:
                pass

    afficher_diagnostic(diagnostic)

    if diagnostic.get("est_une_plante", True):
        plante = diagnostic.get("plante") or "plante"

        # Export PDF (avec les photos analysées)
        try:
            pdf_bytes = generer_pdf(diagnostic, _photos_pour_pdf())
            nom = "".join(c for c in plante.lower().replace(" ", "_") if c.isalnum() or c == "_") or "plante"
            st.download_button(tr("dl_pdf"), data=pdf_bytes, file_name=f"diagnostic_{nom}.pdf", mime="application/pdf")
        except Exception as e:  # noqa: BLE001
            st.caption(f"(PDF: {e})")

        # Rappel d'arrosage (.ics)
        st.markdown(f"#### {tr('sec_reminder')}")
        st.caption(tr("reminder_hint"))
        jours = st.number_input(tr("reminder_every"), min_value=1, max_value=60,
                                value=extraire_jours(diagnostic), step=1)
        try:
            ics_bytes = generer_ics(plante, int(jours))
            st.download_button(tr("dl_ics"), data=ics_bytes,
                               file_name=f"arrosage_{nom}.ics", mime="text/calendar")
        except Exception as e:  # noqa: BLE001
            st.caption(f"(ICS: {e})")

# Pied de page
st.markdown(
    f"""<div style="text-align:center; margin-top:2.5rem; color:#7a9c83; font-size:.8rem; font-weight:600;">
    {tr('footer', v=VERSION, d=VERSION_DATE)}</div>""",
    unsafe_allow_html=True,
)
