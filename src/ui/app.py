import os

import chromadb
import pandas as pd
import requests
import streamlit as st

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"
SOURCE_TYPES = ("url", "gdrive_folder", "pdf", "docx")

st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
st.title("Tableau de bord RAG")

st.header("1) Lancer une ingestion (via n8n)")
webhook = st.text_input("URL Webhook n8n (production)", "https://EXEMPLE.webhook.url/ingestion")

with st.form("ingest"):
    source = st.text_input("URL / ID GDrive / Chemin", "https://eduscol.education.fr/...")
    source_type = st.selectbox("Type", SOURCE_TYPES)
    col1, col2, col3 = st.columns(3)
    with col1:
        matiere = st.text_input("Matière", "NSI")
        voie = st.selectbox("Voie", ["générale", "technologique", "commun"])
    with col2:
        niveau = st.selectbox("Niveau", ["Première", "Terminale"])
        document_type = st.selectbox(
            "Doc type",
            ["programme_officiel", "annale_bac", "cours", "fiche_pedagogique"],
        )
    with col3:
        annee = st.number_input("Année", min_value=2010, max_value=2035, value=2024)
    submitted = st.form_submit_button("Envoyer")
    if submitted:
        if not webhook.startswith("http"):
            st.error("URL webhook invalide")
        else:
            payload = {
                "source": source,
                "source_type": source_type,
                "hints": {
                    "matiere": matiere,
                    "voie": voie,
                    "niveau": niveau,
                    "document_type": document_type,
                    "annee_programme": annee,
                },
            }
            try:
                response = requests.post(webhook, json=payload, timeout=30)
            except requests.RequestException as exc:
                st.error(f"Erreur webhook: {exc}")
            else:
                st.success(f"n8n → {response.status_code}: {response.text[:200]}...")

st.header("2) Explorer Chroma")
try:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(COLLECTION)
    st.info(f"Collection '{COLLECTION}' – {collection.count()} documents")
    query = st.text_input("Requête sémantique", "définition de la dérivée (Terminale)")
    top_k = st.slider("Résultats", 1, 20, 5)
    if st.button("Rechercher"):
        results = collection.query(query_texts=[query], n_results=top_k)
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        distances = results.get("distances", [])
        if docs and metas and distances and docs[0]:
            for offset, (doc, meta, distance) in enumerate(zip(docs[0], metas[0], distances[0]), start=1):
                metadata = meta if isinstance(meta, dict) else {}
                with st.expander(f"Résultat #{offset} — distance {distance:.4f}"):
                    modality = metadata.get("modality")
                    if modality:
                        st.caption(f"Modalité : `{modality}`")
                    st.text_area("Extrait", doc, height=200)
                    st.dataframe(pd.DataFrame(list(metadata.items()), columns=["Champ", "Valeur"]))
        else:
            st.warning("Aucun résultat.")
except Exception as exc:  # pragma: no cover - UI guard
    st.error(f"Chroma indisponible: {exc}")
