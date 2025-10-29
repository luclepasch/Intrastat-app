import streamlit as st
import fitz  # PyMuPDF
import re
import pandas as pd
import io

def extract_intrastat_data(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()

    tva_match = re.search(r"(LU\\d{8,})", text)
    pays_origine = "BE"
    pays_destination = "LU"
    code_nc8 = "62034300"
    nature_transaction = "11"
    mode_transport = "3"
    unite = "PCE"
    type_flux = "D"
    periode = "202410"

    valeur_match = re.search(r"Total H\\.T\\. € (\\d+,\\d+)", text)
    quantite_match = re.search(r"Pièce\\s+(\\d+)", text)

    data = {
        "Période": periode,
        "Type flux": type_flux,
        "Pays origine": pays_origine,
        "Pays destination": pays_destination,
        "TVA partenaire": tva_match.group(1) if tva_match else "",
        "Code NC8": code_nc8,
        "Valeur facture": valeur_match.group(1).replace(",", ".") if valeur_match else "",
        "Masse nette": quantite_match.group(1) if quantite_match else "",
        "Unité": unite,
        "Nature transaction": nature_transaction,
        "Mode transport": mode_transport
    }

    return data

st.title("📦 Générateur Intrastat à partir de factures PDF")
st.write("Chargez vos factures PDF pour générer un fichier Intrastat compatible avec IDEP.WEB du STATEC.")

uploaded_files = st.file_uploader("📤 Uploader une ou plusieurs factures PDF", type=["pdf"], accept_multiple_files=True)

if uploaded_files:
    intrastat_rows = []
    for uploaded_file in uploaded_files:
        data = extract_intrastat_data(uploaded_file)
        intrastat_rows.append(data)

    df = pd.DataFrame(intrastat_rows)

    st.write("✅ Aperçu des données extraites :")
    st.dataframe(df)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, sep=";", index=False)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    st.download_button(
        label="📥 Télécharger le fichier Intrastat (CSV)",
        data=csv_bytes,
        file_name="intrastat_export.csv",
        mime="text/csv"
    )