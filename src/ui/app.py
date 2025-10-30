import os
from collections.abc import Mapping, Sequence
from typing import Any

import chromadb
import pandas as pd
import requests
import streamlit as st
from chromadb import errors as chroma_errors

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"
N8N_DEFAULT_WEBHOOK = os.getenv("N8N_DEFAULT_WEBHOOK", "")
WEBHOOK_TIMEOUT = float(os.getenv("UI_WEBHOOK_TIMEOUT", "10"))
UI_MAX_K = max(1, int(os.getenv("UI_MAX_K", "8")))
UI_DEFAULT_K = min(max(int(os.getenv("UI_DEFAULT_K", "4")), 1), UI_MAX_K)


@st.cache_resource(show_spinner=False)
def _chromadb_collection():
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection(COLLECTION)


@st.cache_data(ttl=30, show_spinner=False)
def _collection_count() -> int:
    return _chromadb_collection().count()


def _call_webhook(url: str, body: dict[str, Any]) -> requests.Response:
    response = requests.post(url, json=body, timeout=WEBHOOK_TIMEOUT)
    response.raise_for_status()
    return response


def _query_chroma(collection, query_text: str, n_results: int):
    return collection.query(query_texts=[query_text], n_results=n_results)

st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
st.title("Tableau de bord RAG")

st.header("1) Lancer une ingestion (via n8n)")
webhook_default = N8N_DEFAULT_WEBHOOK or "https://EXEMPLE.webhook.url/ingestion"
webhook = st.text_input("URL Webhook n8n (production)", webhook_default)
with st.form("ingest"):
    source = st.text_input("URL / ID GDrive / Chemin", "https://eduscol.education.fr/...")
    source_type = st.selectbox("Type", ["url", "gdrive_folder", "pdf", "docx"])
    c1, c2, c3 = st.columns(3)
    with c1:
        matiere = st.text_input("Matière", "NSI")
        voie = st.selectbox("Voie", ["générale", "technologique", "commun"])
    with c2:
        niveau = st.selectbox("Niveau", ["Première", "Terminale"])
        doc_type = st.selectbox(
            "Doc type",
            ["programme_officiel", "annale_bac", "cours", "fiche_pedagogique"],
        )
    with c3:
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
                _call_webhook(webhook, payload)
                st.success("Webhook accepté par n8n (voir journaux n8n pour le détail)")
            except requests.HTTPError as exc:
                st.error(f"n8n a renvoyé {exc.response.status_code}: vérifier le workflow")
            except requests.RequestException as exc:
                st.error(f"Erreur réseau webhook: {exc}")

st.header("2) Explorer Chroma")
try:
    col = _chromadb_collection()
    count = _collection_count()
    st.info(f"Collection '{COLLECTION}' – {count} documents")
    q = st.text_input("Requête sémantique", "définition de la dérivée (Terminale)")
    k = st.slider("Résultats", 1, UI_MAX_K, UI_DEFAULT_K)
    if st.button("Rechercher"):
        with st.spinner("Interrogation de Chroma..."):
            res = _query_chroma(col, q, k)
        documents: Sequence[Sequence[str]] | None = res.get("documents")
        metadatas: Sequence[Sequence[Mapping[str, Any]]] | None = res.get("metadatas")
        distances: Sequence[Sequence[float]] | None = res.get("distances")
        if not documents or not metadatas or not distances:
            st.warning("Aucun résultat.")
        else:
            first_docs = documents[0]
            first_metas = metadatas[0]
            first_distances = distances[0]
            for i, doc in enumerate(first_docs):
                distance = first_distances[i] if i < len(first_distances) else float("nan")
                metadata = first_metas[i] if i < len(first_metas) else {}
                with st.expander(f"Résultat #{i+1}  — distance {distance:.4f}"):
                    st.text_area("Extrait", doc, height=200)
                    st.dataframe(pd.DataFrame(list(metadata.items()), columns=["Champ", "Valeur"]))
except (chroma_errors.ChromaError, requests.RequestException, ValueError) as exc:
    st.error(f"Chroma indisponible: {exc}")
