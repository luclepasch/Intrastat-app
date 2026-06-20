"""
disclaimer.py — Page d'avertissement (disclaimer), multilingue.
"""

from __future__ import annotations

import streamlit as st

import i18n


def render_disclaimer() -> None:
    st.markdown(i18n.tr("disclaimer_title"))
    st.markdown(i18n.tr("disclaimer_md"))
    st.caption(i18n.tr("disclaimer_caption"))
