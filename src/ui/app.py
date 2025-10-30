import os
from typing import Any, Mapping, Sequence, cast

import chromadb
import pandas as pd
import requests
import streamlit as st

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"

st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
st.title("Tableau de bord RAG")

st.header("1) Lancer une ingestion (via n8n)")
webhook = st.text_input(
    "URL Webhook n8n (production)", "https://EXEMPLE.webhook.url/ingestion"
)
with st.form("ingest"):
    source = st.text_input(
        "URL / ID GDrive / Chemin", "https://eduscol.education.fr/..."
    )
    source_type = st.selectbox(
        "Type", ["url", "gdrive_folder", "pdf", "docx", "py_dir"]
    )
    col_meta, col_level, col_year = st.columns(3)

    with col_meta:
        matiere = st.text_input("Matière", "NSI")
        voie = st.selectbox("Voie", ["générale", "technologique", "commun"])

    with col_level:
        niveau = st.selectbox("Niveau", ["Première", "Terminale"])
        doc_type = st.selectbox(
            "Doc type",
            ["programme_officiel", "annale_bac", "cours", "fiche_pedagogique"],
        )

    with col_year:
        annee = st.number_input("Année", min_value=2010, max_value=2035, value=2024)

    if st.form_submit_button("Envoyer"):
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
                    "document_type": doc_type,
                    "annee_programme": annee,
                },
            }
            try:
                response = requests.post(webhook, json=payload, timeout=30)
                st.success(
                    f"n8n → {response.status_code}: {response.text[:200]}..."
                )
            except requests.RequestException as error:
                st.error(f"Erreur webhook: {error}")

st.header("2) Explorer Chroma")
try:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(COLLECTION)
    st.info(f"Collection '{COLLECTION}' – {collection.count()} documents")
    query = st.text_input("Requête sémantique", "définition de la dérivée (Terminale)")
    top_k = st.slider("Résultats", 1, 20, 5)
    if st.button("Rechercher"):
        raw_result = cast(
            Mapping[str, Sequence[Sequence[Any]]],
            collection.query(query_texts=[query], n_results=top_k),
        )
        documents = cast(
            Sequence[Sequence[str]], raw_result.get("documents") or []
        )
        metadatas = cast(
            Sequence[Sequence[Mapping[str, Any]]],
            raw_result.get("metadatas") or [],
        )
        distances = cast(
            Sequence[Sequence[float]], raw_result.get("distances") or []
        )

        if not documents or not metadatas or not distances:
            st.warning("Aucun résultat.")
        else:
            first_docs = documents[0]
            first_metas = metadatas[0]
            first_distances = distances[0]
            for idx, doc in enumerate(first_docs):
                distance = first_distances[idx] if idx < len(first_distances) else 0.0
                metadata = first_metas[idx] if idx < len(first_metas) else {}
                with st.expander(
                    f"Résultat #{idx + 1}  — distance {distance:.4f}"
                ):
                    st.text_area("Extrait", doc, height=200)
                    st.dataframe(
                        pd.DataFrame(
                            list(metadata.items()),
                            columns=["Champ", "Valeur"],
                        )
                    )
except Exception as error:  # pragma: no cover - UI fallback
    st.error(f"Chroma indisponible: {error}")
