"""
admin.py — Interface d'administration des utilisateurs (réservée ADMIN).

Fonctions :
  - liste et recherche des utilisateurs
  - changement de rôle (ADMIN / USER)
  - activation / désactivation des comptes
  - réinitialisation du mot de passe
  - suppression d'un compte
"""

from __future__ import annotations

import streamlit as st

import auth
import database as db


@auth.require_role("ADMIN")
def render_admin() -> None:
    """Affiche le panneau d'administration (protégé par le rôle ADMIN)."""
    st.markdown("## 🛠️ Administration des utilisateurs")

    current = auth.get_current_user()

    # --- Création rapide d'un utilisateur ---
    with st.expander("➕ Créer un utilisateur"):
        with st.form("admin_create"):
            c1, c2 = st.columns(2)
            email = c1.text_input("E-mail")
            full_name = c2.text_input("Nom complet")
            c3, c4 = st.columns(2)
            password = c3.text_input("Mot de passe", type="password")
            role = c4.selectbox("Rôle", auth.ROLES, index=auth.ROLES.index("USER"))
            ok = st.form_submit_button("Créer")
        if ok:
            success, msg = auth.register_user(email, password, full_name, role)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    # --- Recherche ---
    search = st.text_input("🔎 Rechercher (e-mail ou nom)", key="admin_search")
    users = db.list_users(search)

    st.caption(f"{len(users)} utilisateur(s)")

    # --- Liste des utilisateurs ---
    for u in users:
        actif = bool(int(u.get("is_active", 1)))
        badge = "🟢" if actif else "🔴"
        titre = f"{badge} {u['email']}  ·  {u['role']}"
        with st.expander(titre):
            st.markdown(
                f"**ID :** {u['id']}  ·  **Nom :** {u.get('full_name') or '—'}  \n"
                f"**Créé le :** {u.get('created_at') or '—'}  ·  "
                f"**Dernière connexion :** {u.get('last_login_at') or '—'}  \n"
                f"**Échecs de connexion :** {u.get('failed_attempts', 0)}"
            )

            est_soi_meme = current and current["id"] == u["id"]

            col1, col2 = st.columns(2)

            # Changement de rôle
            with col1:
                nouveau_role = st.selectbox(
                    "Rôle", auth.ROLES, index=auth.ROLES.index(u["role"]),
                    key=f"role_{u['id']}",
                    disabled=est_soi_meme,  # on ne change pas son propre rôle
                )
                if not est_soi_meme and st.button("Appliquer le rôle", key=f"role_btn_{u['id']}"):
                    db.update_role(u["id"], nouveau_role)
                    st.success(f"Rôle mis à jour : {nouveau_role}")
                    st.rerun()

            # Activation / désactivation
            with col2:
                if est_soi_meme:
                    st.info("Vous ne pouvez pas désactiver votre propre compte.")
                elif actif:
                    if st.button("🔴 Désactiver", key=f"deact_{u['id']}"):
                        db.set_active(u["id"], False)
                        st.rerun()
                else:
                    if st.button("🟢 Activer", key=f"act_{u['id']}"):
                        db.set_active(u["id"], True)
                        st.rerun()

            # Réinitialisation du mot de passe
            with st.form(f"reset_{u['id']}"):
                new_pw = st.text_input(
                    "Nouveau mot de passe", type="password", key=f"pw_{u['id']}"
                )
                reset = st.form_submit_button("🔑 Réinitialiser le mot de passe")
            if reset:
                if len(new_pw) < auth.MIN_PASSWORD_LEN:
                    st.error(f"Au moins {auth.MIN_PASSWORD_LEN} caractères requis.")
                else:
                    db.update_password(u["id"], auth.hash_password(new_pw))
                    db.reset_failed(u["id"])
                    st.success("Mot de passe réinitialisé.")

            # Quotas d'analyses (0 = pas de limite pour cette période)
            with st.form(f"quota_{u['id']}"):
                st.markdown("**Quotas d'analyses** (0 = illimité)")
                q1, q2, q3, q4 = st.columns(4)
                qd = q1.number_input("Jour", min_value=0, step=1,
                                     value=int(u.get("quota_day") or 0), key=f"qd_{u['id']}")
                qw = q2.number_input("Semaine", min_value=0, step=1,
                                     value=int(u.get("quota_week") or 0), key=f"qw_{u['id']}")
                qm = q3.number_input("Mois", min_value=0, step=1,
                                     value=int(u.get("quota_month") or 0), key=f"qm_{u['id']}")
                qy = q4.number_input("An", min_value=0, step=1,
                                     value=int(u.get("quota_year") or 0), key=f"qy_{u['id']}")
                quota_ok = st.form_submit_button("💾 Enregistrer les quotas")
            if quota_ok:
                db.set_user_quota(
                    u["id"],
                    int(qd) or None, int(qw) or None, int(qm) or None, int(qy) or None,
                )
                st.success("Quotas mis à jour.")
                st.rerun()

            # Suppression
            if not est_soi_meme:
                if st.button("🗑️ Supprimer ce compte", key=f"del_{u['id']}"):
                    db.delete_user(u["id"])
                    st.warning("Compte supprimé.")
                    st.rerun()
