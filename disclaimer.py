"""
disclaimer.py — Page d'avertissement (disclaimer).
"""

from __future__ import annotations

import streamlit as st


def render_disclaimer() -> None:
    st.markdown("## ⚠️ Avertissement / Disclaimer")
    st.markdown(
        """
**Plant Doctor** fournit un diagnostic généré par une **intelligence artificielle**,
à titre purement **informatif et indicatif**.

- Les résultats peuvent comporter des **erreurs** et ne remplacent pas l'avis d'un
  professionnel (pépiniériste, jardinerie, service phytosanitaire, agronome).
- N'appliquez aucun traitement (produit, engrais, pesticide…) sans vérifier son
  **adéquation, son dosage et la réglementation** en vigueur dans votre pays.
- Les **astuces de grand-mère** sont proposées à titre traditionnel et doivent être
  utilisées avec prudence.
- Aucune garantie n'est donnée quant à l'exactitude de l'identification ou des
  recommandations.
- Vos photos et analyses sont **stockées** pour constituer votre historique ; vous
  pouvez les supprimer à tout moment depuis l'application.

En utilisant l'application, vous reconnaissez que son éditeur ne saurait être tenu
responsable de tout dommage résultant de l'usage des informations fournies.
"""
    )
    st.caption("Diagnostic IA — à titre indicatif. En cas de doute, consultez un professionnel.")
