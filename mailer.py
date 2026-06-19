"""
mailer.py — Envoi d'e-mails (notification d'inscription à l'administrateur).

Configuration (st.secrets ou variables d'environnement) :
  SMTP_HOST          : serveur SMTP (ex: smtp.gmail.com)
  SMTP_PORT          : port (587 STARTTLS, 465 SSL ; défaut 587)
  SMTP_USER          : identifiant SMTP (souvent l'adresse e-mail)
  SMTP_PASSWORD      : mot de passe / mot de passe d'application
  SMTP_FROM          : adresse expéditrice (ex: noreply@mondomaine.com)
  SMTP_USE_TLS       : "true"/"false" (STARTTLS, défaut true ; ignoré si port 465)
  ADMIN_NOTIFY_EMAIL : destinataire des notifications (défaut : ADMIN_EMAIL)

Si SMTP n'est pas configuré, l'envoi est ignoré silencieusement
(l'inscription reste visible dans l'administration).
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import database as db


def _cfg(key: str, default=None):
    return db.get_config(key, default)


def email_configured() -> bool:
    """Vrai si la configuration SMTP minimale est présente."""
    return bool(_cfg("SMTP_HOST") and _cfg("SMTP_FROM"))


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Envoie un e-mail. Renvoie (succès, message)."""
    if not email_configured():
        return False, "SMTP non configuré"
    if not to:
        return False, "Destinataire manquant"

    host = _cfg("SMTP_HOST")
    port = int(_cfg("SMTP_PORT") or 587)
    user = _cfg("SMTP_USER")
    password = _cfg("SMTP_PASSWORD")
    sender = _cfg("SMTP_FROM")
    use_tls = str(_cfg("SMTP_USE_TLS", "true")).strip().lower() in ("1", "true", "yes", "on")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if port == 465:  # SSL implicite
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as srv:
                if user:
                    srv.login(user, password)
                srv.send_message(msg)
        else:  # STARTTLS
            with smtplib.SMTP(host, port, timeout=15) as srv:
                if use_tls:
                    srv.starttls(context=ssl.create_default_context())
                if user:
                    srv.login(user, password)
                srv.send_message(msg)
        return True, "E-mail envoyé"
    except Exception as exc:  # noqa: BLE001
        return False, f"Échec de l'envoi : {exc}"


def notify_admin_new_registration(user_email: str, full_name: str, plan: str = "FREE") -> tuple[bool, str]:
    """Notifie l'administrateur qu'une inscription attend validation."""
    admin = _cfg("ADMIN_NOTIFY_EMAIL") or _cfg("ADMIN_EMAIL")
    if not admin:
        return False, "Aucune adresse administrateur configurée"
    subject = "🌿 Plant Doctor — nouvelle inscription à valider"
    body = (
        "Une nouvelle inscription est en attente de validation :\n\n"
        f"  Nom    : {full_name or '—'}\n"
        f"  E-mail : {user_email}\n"
        f"  Plan   : {plan}\n\n"
        "Connectez-vous à l'espace d'administration (onglet « Tableau de bord ») "
        "pour approuver ou rejeter ce compte."
    )
    return send_email(admin, subject, body)
