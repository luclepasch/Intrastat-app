"""
admin.py — Interface d'administration (réservée ADMIN).

Deux onglets :
  - 📊 Tableau de bord : statistiques (utilisateurs, analyses, graphiques)
  - 👥 Utilisateurs     : liste, recherche, rôle, activation, reset MDP, quotas
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import auth
import database as db
import quotas


# --------------------------------------------------------------------------- #
# Onglet : Tableau de bord
# --------------------------------------------------------------------------- #
def _render_dashboard() -> None:
    # --- Inscriptions en attente de validation ---
    pending = db.list_pending_users()
    if pending:
        st.markdown(f"### 🕐 Inscriptions en attente ({len(pending)})")
        for u in pending:
            cols = st.columns([4, 1, 1])
            cols[0].markdown(
                f"**{u['email']}** · {u.get('full_name') or '—'} · "
                f"formule **{u.get('plan') or 'FREE'}**"
            )
            if cols[1].button("✅ Approuver", key=f"appr_{u['id']}"):
                db.set_active(u["id"], True)
                st.success(f"{u['email']} approuvé.")
                st.rerun()
            if cols[2].button("✖️ Rejeter", key=f"rej_{u['id']}"):
                db.delete_user(u["id"])
                st.rerun()
        st.divider()

    st.markdown("### 📊 Vue d'ensemble")

    s = db.users_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Utilisateurs", s["total"])
    c2.metric("🟢 Actifs", s["actifs"])
    c3.metric("🛡️ Admins", s["admins"])
    c4.metric("🔬 Analyses (total)", db.usage_total())

    if s["inactifs"] or s["verrouilles"]:
        st.caption(f"🔴 Inactifs : {s['inactifs']}  ·  🔒 Verrouillés : {s['verrouilles']}")

    # --- Analyses par période ---
    now = datetime.utcnow()
    jour0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    debuts = {
        "jour": jour0,
        "semaine": jour0 - timedelta(days=now.weekday()),
        "mois": jour0.replace(day=1),
        "an": jour0.replace(month=1, day=1),
    }
    st.markdown("### 🔬 Analyses effectuées")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Aujourd'hui", db.usage_global_since(debuts["jour"].isoformat(timespec="seconds")))
    p2.metric("Cette semaine", db.usage_global_since(debuts["semaine"].isoformat(timespec="seconds")))
    p3.metric("Ce mois", db.usage_global_since(debuts["mois"].isoformat(timespec="seconds")))
    p4.metric("Cette année", db.usage_global_since(debuts["an"].isoformat(timespec="seconds")))

    # --- Graphique des 14 derniers jours ---
    st.markdown("### 📈 Analyses sur 14 jours")
    jours = [jour0 - timedelta(days=i) for i in range(13, -1, -1)]
    rows = db.usage_by_day(jours[0].isoformat(timespec="seconds")) or []
    counts = {r["jour"]: int(r["n"]) for r in rows}
    chart = pd.DataFrame({
        "Date": [d.strftime("%d/%m") for d in jours],
        "Analyses": [counts.get(d.strftime("%Y-%m-%d"), 0) for d in jours],
    })
    st.bar_chart(chart, x="Date", y="Analyses", color="#16a34a")

    # --- Top utilisateurs ---
    st.markdown("### 🏆 Top utilisateurs")
    top = db.top_users_by_usage(10)
    if top:
        df = pd.DataFrame(top).rename(columns={"email": "E-mail", "role": "Rôle", "n": "Analyses"})
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.caption("Aucune donnée.")

    # --- Activité récente ---
    st.markdown("### 🕑 Activité récente")
    recent = db.recent_usage(15)
    if recent:
        df = pd.DataFrame(recent).rename(columns={"email": "E-mail", "created_at": "Date (UTC)"})
        st.dataframe(df, hide_index=True, use_container_width=True)
    else:
        st.caption("Aucune analyse pour le moment.")

    # --- Rétention & purge de l'historique ---
    st.markdown("### 🗓️ Rétention de l'historique")
    stockees = db.count_stored_analyses()
    cutoff = db.retention_cutoff_iso()
    st.caption(
        f"Analyses stockées : **{stockees}**  ·  "
        + ("Purge automatique : **désactivée** (ANALYSIS_RETENTION_MONTHS non défini)."
           if not cutoff else
           f"Purge automatique active : suppression au-delà de la limite configurée "
           f"(avant {cutoff[:10]}).")
    )
    with st.expander("🗑️ Purger manuellement"):
        mois = st.number_input("Supprimer les analyses de plus de (mois)",
                               min_value=1, max_value=120, value=12, step=1)
        c = (datetime.utcnow() - timedelta(days=int(mois) * 30)).isoformat(timespec="seconds")
        concernees = db.count_analyses_before(c)
        st.caption(f"{concernees} analyse(s) seraient supprimée(s).")
        if st.button("Purger maintenant", disabled=concernees == 0):
            db.delete_analyses_before(c)
            st.success(f"{concernees} analyse(s) supprimée(s).")
            st.rerun()


# --------------------------------------------------------------------------- #
# Onglet : Gestion des utilisateurs
# --------------------------------------------------------------------------- #
def _render_users() -> None:
    current = auth.get_current_user()

    # --- Création rapide d'un utilisateur ---
    with st.expander("➕ Créer un utilisateur"):
        with st.form("admin_create"):
            t1, t2, t3 = st.columns([1, 2, 2])
            title = t1.selectbox("Titre", auth.TITRES)
            first_name = t2.text_input("Prénom")
            last_name = t3.text_input("Nom")
            email = st.text_input("E-mail")
            c3, c4, c5 = st.columns(3)
            password = c3.text_input("Mot de passe", type="password")
            role = c4.selectbox("Rôle", auth.ROLES, index=auth.ROLES.index("USER"))
            plan = c5.selectbox("Formule", quotas.PLANS, index=quotas.PLANS.index("FREE"))
            ok = st.form_submit_button("Créer")
        if ok:
            # Compte créé par l'admin : actif immédiatement
            success, msg = auth.register_user(
                email, password, first_name=first_name, last_name=last_name,
                title=title, role=role, plan=plan, active=True)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    # --- Recherche ---
    search = st.text_input("🔎 Rechercher (e-mail ou nom)", key="admin_search")
    users = db.list_users(search)
    st.caption(f"{len(users)} utilisateur(s)")

    for u in users:
        actif = bool(int(u.get("is_active", 1)))
        badge = "🟢" if actif else "🔴"
        with st.expander(f"{badge} {u['email']}  ·  {u['role']}"):
            st.markdown(
                f"**ID :** {u['id']}  ·  **Titre :** {u.get('title') or '—'}  ·  "
                f"**Prénom :** {u.get('first_name') or '—'}  ·  "
                f"**Nom :** {u.get('last_name') or '—'}  ·  "
                f"**Formule :** {u.get('plan') or 'FREE'}  \n"
                f"**Créé le :** {u.get('created_at') or '—'}  ·  "
                f"**Dernière connexion :** {u.get('last_login_at') or '—'}  \n"
                f"**Échecs de connexion :** {u.get('failed_attempts', 0)}"
            )

            # Édition de l'identité (titre / prénom / nom)
            with st.form(f"identity_{u['id']}"):
                i1, i2, i3 = st.columns([1, 2, 2])
                t_cur = u.get("title") or ""
                t_idx = auth.TITRES.index(t_cur) if t_cur in auth.TITRES else 0
                new_title = i1.selectbox("Titre", auth.TITRES, index=t_idx, key=f"t_{u['id']}")
                new_first = i2.text_input("Prénom", value=u.get("first_name") or "", key=f"fn_{u['id']}")
                new_last = i3.text_input("Nom", value=u.get("last_name") or "", key=f"ln_{u['id']}")
                if st.form_submit_button("💾 Enregistrer l'identité"):
                    db.update_user_identity(u["id"], new_title, new_first, new_last)
                    st.success("Identité mise à jour.")
                    st.rerun()

            # Coordonnées (signalétique)
            with st.form(f"details_{u['id']}"):
                st.markdown("**Coordonnées**")
                vals = {}
                dcols = st.columns(2)
                for i, (col, label) in enumerate(db.USER_DETAIL_FIELDS):
                    vals[col] = dcols[i % 2].text_input(
                        label, value=u.get(col) or "", key=f"d_{col}_{u['id']}")
                if st.form_submit_button("💾 Enregistrer les coordonnées"):
                    db.update_user_details(u["id"], vals)
                    st.success("Coordonnées mises à jour.")
                    st.rerun()

            est_soi_meme = current and current["id"] == u["id"]
            col1, col2 = st.columns(2)

            # Rôle
            with col1:
                nouveau_role = st.selectbox(
                    "Rôle", auth.ROLES, index=auth.ROLES.index(u["role"]),
                    key=f"role_{u['id']}", disabled=est_soi_meme,
                )
                if not est_soi_meme and st.button("Appliquer le rôle", key=f"role_btn_{u['id']}"):
                    db.update_role(u["id"], nouveau_role)
                    st.success(f"Rôle mis à jour : {nouveau_role}")
                    st.rerun()

            # Formule (plan) — définit les quotas par défaut
            with col2:
                plan_actuel = u.get("plan") or "FREE"
                idx = quotas.PLANS.index(plan_actuel) if plan_actuel in quotas.PLANS else 0
                nouveau_plan = st.selectbox("Formule", quotas.PLANS, index=idx, key=f"plan_{u['id']}")
                if st.button("Appliquer la formule", key=f"plan_btn_{u['id']}"):
                    db.set_user_plan(u["id"], nouveau_plan)
                    st.success(f"Formule mise à jour : {nouveau_plan}")
                    st.rerun()

            # Activation / désactivation
            if est_soi_meme:
                st.info("Vous ne pouvez pas désactiver votre propre compte.")
            elif actif:
                if st.button("🔴 Désactiver", key=f"deact_{u['id']}"):
                    db.set_active(u["id"], False)
                    st.rerun()
            else:
                if st.button("🟢 Activer le compte", key=f"act_{u['id']}"):
                    db.set_active(u["id"], True)
                    st.rerun()

            # Reset mot de passe
            with st.form(f"reset_{u['id']}"):
                new_pw = st.text_input("Nouveau mot de passe", type="password", key=f"pw_{u['id']}")
                reset = st.form_submit_button("🔑 Réinitialiser le mot de passe")
            if reset:
                if len(new_pw) < auth.MIN_PASSWORD_LEN:
                    st.error(f"Au moins {auth.MIN_PASSWORD_LEN} caractères requis.")
                else:
                    db.update_password(u["id"], auth.hash_password(new_pw))
                    db.reset_failed(u["id"])
                    st.success("Mot de passe réinitialisé.")

            # Quotas d'analyses (0 = illimité)
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


# --------------------------------------------------------------------------- #
# Page admin
# --------------------------------------------------------------------------- #
@auth.require_role("ADMIN")
def render_admin() -> None:
    """Affiche le panneau d'administration (protégé par le rôle ADMIN)."""
    st.markdown("## 🛠️ Administration")
    tab_dash, tab_users = st.tabs(["📊 Tableau de bord", "👥 Utilisateurs"])
    with tab_dash:
        _render_dashboard()
    with tab_users:
        _render_users()
