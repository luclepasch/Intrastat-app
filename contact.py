"""
contact.py — Formulaire de contact.

Permet à un utilisateur connecté d'envoyer un message à l'administrateur
(par e-mail si SMTP est configuré, sinon affiche l'adresse de contact).
"""

from __future__ import annotations

import streamlit as st

import auth
import database as db

try:
    import mailer
except Exception:  # pragma: no cover
    mailer = None


@auth.require_role("USER")  # tout utilisateur connecté
def render_contact() -> None:
    st.markdown("## 📨 Contact")
    user = auth.get_current_user()
    st.caption("Une question, un problème ou une suggestion ? Écrivez-nous.")

    with st.form("contact_form"):
        sujet = st.text_input("Sujet")
        message = st.text_area("Message", height=180)
        envoyer = st.form_submit_button("Envoyer")

    if envoyer:
        if not message.strip():
            st.error("Veuillez saisir un message.")
            return

        admin = db.get_config("ADMIN_NOTIFY_EMAIL") or db.get_config("ADMIN_EMAIL")
        corps = (
            "Nouveau message via le formulaire de contact :\n\n"
            f"De     : {user.get('full_name') or '—'} <{user.get('email')}>\n"
            f"Sujet  : {sujet or '(sans sujet)'}\n\n"
            f"{message}"
        )

        sent = False
        if mailer and mailer.email_configured() and admin:
            ok, _info = mailer.send_email(
                admin, f"[Plant Doctor] Contact — {sujet or 'message'}", corps)
            sent = ok

        if sent:
            st.success("✅ Message envoyé. Merci, nous vous répondrons par e-mail.")
        elif admin:
            st.info(f"📧 Envoi automatique indisponible. Écrivez-nous directement à : **{admin}**")
        else:
            st.warning("Aucune adresse de contact n'est configurée pour le moment.")
