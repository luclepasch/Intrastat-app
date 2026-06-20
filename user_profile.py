"""
profile.py — Page de profil utilisateur.

Accessible à tout utilisateur connecté. Permet de :
  - consulter ses informations de compte
  - modifier son nom complet
  - changer son propre mot de passe (avec vérification de l'actuel)
"""

from __future__ import annotations

import streamlit as st

import auth
import database as db
import i18n
import quotas


@auth.require_role("USER")  # tout utilisateur authentifié (ADMIN inclus)
def render_profile() -> None:
    """Affiche la page de profil de l'utilisateur courant."""
    current = auth.get_current_user()
    user = db.get_user_by_id(current["id"])  # données fraîches depuis la base
    if not user:
        st.error("Profil introuvable.")
        return

    st.markdown("## 👤 Mon profil")

    # --- Informations du compte ---
    st.markdown(
        f"**E-mail :** {user['email']}  \n"
        f"**Rôle :** {user['role']}  \n"
        f"**Compte créé le :** {user.get('created_at') or '—'}  \n"
        f"**Dernière connexion :** {user.get('last_login_at') or '—'}"
    )

    # Formule & quota d'analyses
    st.markdown(f"### 💳 Formule : {user.get('plan') or 'FREE'}")
    st.write(quotas.quota_caption(user["id"]) or "Illimité")

    st.divider()

    # --- Langue préférée ---
    st.markdown("### 🌐 Langue")
    noms = list(i18n.LANGUES.keys())
    codes = list(i18n.LANGUES.values())
    cur = i18n.current_lang()
    idx = codes.index(cur) if cur in codes else 0
    choix = st.selectbox("Langue préférée", noms, index=idx, key="profile_lang")
    if st.button("Enregistrer la langue", key="save_lang"):
        i18n.set_language(i18n.LANGUES[choix], user["id"])
        st.success("Langue enregistrée.")
        st.rerun()

    st.divider()

    # --- Modifier l'identité (titre / prénom / nom) ---
    st.markdown("### ✏️ Mon identité")
    with st.form("profile_identity"):
        p1, p2, p3 = st.columns([1, 2, 2])
        t_cur = user.get("title") or ""
        t_idx = auth.TITRES.index(t_cur) if t_cur in auth.TITRES else 0
        title = p1.selectbox("Titre", auth.TITRES, index=t_idx)
        first_name = p2.text_input("Prénom", value=user.get("first_name") or "")
        last_name = p3.text_input("Nom", value=user.get("last_name") or "")
        ok = st.form_submit_button("Enregistrer")
    if ok:
        success, msg = auth.update_profile_identity(user["id"], title, first_name, last_name)
        if success:
            st.success(msg)
            st.rerun()
        else:
            st.error(msg)

    st.divider()

    # --- Changer le mot de passe ---
    st.markdown("### 🔑 Changer mon mot de passe")
    with st.form("profile_password"):
        current_pw = st.text_input("Mot de passe actuel", type="password")
        new_pw = st.text_input("Nouveau mot de passe", type="password")
        confirm_pw = st.text_input("Confirmer le nouveau mot de passe", type="password")
        st.caption(f"Au moins {auth.MIN_PASSWORD_LEN} caractères.")
        submit = st.form_submit_button("Modifier le mot de passe")

    if submit:
        if new_pw != confirm_pw:
            st.error("Les deux nouveaux mots de passe ne correspondent pas.")
        else:
            success, msg = auth.change_password(user["id"], current_pw, new_pw)
            if success:
                st.success(msg)
            else:
                st.error(msg)
