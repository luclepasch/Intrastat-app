"""
contact.py — Formulaire de contact.

Permet à un utilisateur connecté d'envoyer un message à l'administrateur
(par e-mail si SMTP est configuré, sinon affiche l'adresse de contact).
"""

from __future__ import annotations

import streamlit as st

import auth
import database as db
import i18n

try:
    import mailer
except Exception:  # pragma: no cover
    mailer = None


@auth.require_role("USER")  # tout utilisateur connecté
def render_contact() -> None:
    st.markdown(i18n.tr("contact_title"))
    user = auth.get_current_user()
    st.caption(i18n.tr("contact_caption"))

    with st.form("contact_form"):
        sujet = st.text_input(i18n.tr("contact_subject"))
        message = st.text_area(i18n.tr("contact_message"), height=180)
        envoyer = st.form_submit_button(i18n.tr("contact_send"))

    if envoyer:
        if not message.strip():
            st.error(i18n.tr("contact_empty"))
            return

        admin = db.get_config("ADMIN_NOTIFY_EMAIL") or db.get_config("ADMIN_EMAIL")
        corps = (
            "Nouveau message via le formulaire de contact :\n\n"
            f"De     : {user.get('full_name') or '—'} <{user.get('email')}>\n"
            f"Sujet  : {sujet or i18n.tr('contact_no_subject')}\n\n"
            f"{message}"
        )

        sent = False
        if mailer and mailer.email_configured() and admin:
            ok, _info = mailer.send_email(
                admin, f"[Plant Doctor] Contact — {sujet or 'message'}", corps)
            sent = ok

        if sent:
            st.success(i18n.tr("contact_sent"))
        elif admin:
            st.info(i18n.tr("contact_fallback", admin=admin))
        else:
            st.warning(i18n.tr("contact_noaddr"))
