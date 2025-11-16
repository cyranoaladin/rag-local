from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import chromadb
import pandas as pd
import requests
import streamlit as st
from chromadb import errors as chroma_errors
from chromadb.config import Settings

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"
WEBHOOK_TIMEOUT = float(os.getenv("UI_WEBHOOK_TIMEOUT", "10"))
INGEST_BASE_URL = os.getenv("INGEST_API_BASE") or os.getenv("INGEST_BASE_URL", "http://ingestor:8001")
INGEST_API_TOKEN = os.getenv("INGEST_API_TOKEN") or os.getenv("INGESTOR_API_TOKEN", "")
# Default to Authorization header with Bearer prefix for production
INGEST_AUTH_HEADER = os.getenv("INGEST_AUTH_HEADER", os.getenv("UI_INGEST_AUTH_HEADER", "Authorization"))
UI_INGEST_AUTH_BEARER_PREFIX = (os.getenv("UI_INGEST_AUTH_BEARER_PREFIX", "true").strip().lower() in {"1", "true", "yes"})
INGEST_TIMEOUT = float(os.getenv("UI_INGEST_TIMEOUT", os.getenv("UI_WEBHOOK_TIMEOUT", "10")))
CHROMA_TIMEOUT = float(os.getenv("CHROMA_REQUEST_TIMEOUT", os.getenv("UI_CHROMA_TIMEOUT", "30")))
UI_MAX_K = max(1, int(os.getenv("UI_MAX_K", "8")))
UI_DEFAULT_K = min(max(int(os.getenv("UI_DEFAULT_K", "4")), 1), UI_MAX_K)
STREAMLIT_IMPORT_ONLY = os.getenv("STREAMLIT_IMPORT_ONLY", "0") == "1"

SOURCE_TYPE_LABELS: dict[str, str] = {
    "url": "URL / Page web",
    # Google Drive désactivé pour V1
    # "gdrive_folder": "Dossier Google Drive",
    "pdf": "PDF local",
    "docx": "Document Word (.docx)",
    "markdown": "Markdown (.md)",
    # "video": "Vidéo (mp4, YouTube, etc.)",
}
SOURCE_PLACEHOLDERS: dict[str, str] = {
    "url": "https://eduscol.education.fr/...",
    # "gdrive_folder": "1xABCDEFGH123456789",
    "pdf": "/data/uploads/ressource.pdf",
    "docx": "/data/uploads/ressource.docx",
    "markdown": "/data/uploads/ressource.md",
    # "video": "/data/uploads/cours.mp4",
}
MULTIMODAL_ONLY_TYPES: set[str] = set()


def _build_metadata_inputs(prefix: str) -> tuple[str, str, dict[str, Any]]:
    options = list(SOURCE_TYPE_LABELS.keys())
    source_type = st.selectbox(
        "Type de source",
        options,
        format_func=lambda key: SOURCE_TYPE_LABELS.get(key, key),
        key=f"{prefix}type",
    )
    placeholder = SOURCE_PLACEHOLDERS.get(source_type, "https://exemple.com")
    source = st.text_input(
        "URL / ID GDrive / Chemin",
        value=st.session_state.get(f"{prefix}source", ""),
        placeholder=placeholder,
        key=f"{prefix}source",
    )
    if source_type in MULTIMODAL_ONLY_TYPES:
        st.caption("🔁 Cette source nécessite le mode 'multimodal' et un fichier local accessible.")
    c1, c2, c3 = st.columns(3)
    with c1:
        matiere = st.text_input("Matière", "NSI", key=f"{prefix}matiere")
        voie = st.selectbox("Voie", ["générale", "technologique", "commun"], key=f"{prefix}voie")
    with c2:
        niveau = st.selectbox("Niveau", ["Première", "Terminale"], key=f"{prefix}niveau")
        doc_type = st.selectbox(
            "Doc type",
            ["programme_officiel", "annale_bac", "cours", "fiche_pedagogique"],
            key=f"{prefix}doctype",
        )
    with c3:
        annee = st.number_input(
            "Année", min_value=2010, max_value=2035, value=2024, key=f"{prefix}annee"
        )
    hints = {
        "matiere": matiere,
        "voie": voie,
        "niveau": niveau,
        "document_type": doc_type,
        "annee_programme": annee,
    }
    return source, source_type, hints


@st.cache_resource(show_spinner=False)
def _chromadb_collection():
    timeout_seconds = max(1, int(CHROMA_TIMEOUT))
    settings = Settings(
        chroma_server_host=CHROMA_HOST,
        chroma_server_http_port=CHROMA_PORT,
        anonymized_telemetry=False,
        chroma_logservice_request_timeout_seconds=timeout_seconds,
        chroma_sysdb_request_timeout_seconds=timeout_seconds,
        chroma_query_request_timeout_seconds=timeout_seconds,
    )
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT, settings=settings)
    return client.get_or_create_collection(COLLECTION)


@st.cache_data(ttl=30, show_spinner=False)
def _collection_count() -> int:
    return _chromadb_collection().count()


def _query_chroma(collection, query_text: str, n_results: int):
    return collection.query(query_texts=[query_text], n_results=n_results)


def _call_ingest_api(
    base_url: str | None,
    token: str | None,
    header_name: str,
    payload: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    if not base_url:
        raise ValueError("Adresse de l'API d'ingestion absente")
    url = f"{base_url.rstrip('/')}/ingest"
    headers = {"Content-Type": "application/json"}
    if token:
        value = token
        if header_name.lower() == "authorization" and UI_INGEST_AUTH_BEARER_PREFIX and not token.lower().startswith("bearer "):
            value = f"Bearer {token}"
        headers[header_name] = value
    response = requests.post(url, params={"mode": mode}, json=payload, headers=headers, timeout=INGEST_TIMEOUT)
    response.raise_for_status()
    return response.json()




def _render_admin_form() -> None:
    st.subheader("Administration – Appels directs API")
    st.warning(
        "Protègez impérativement cette section derrière l'authentification Basic Auth configurée dans Nginx.",
        icon="🔒",
    )
    with st.form("direct_ingest"):
        api_base_input = st.text_input("Base URL API", INGEST_BASE_URL, key="direct_api_base")
        api_token_input = st.text_input(
            "Jeton API (optionnel)", INGEST_API_TOKEN, type="password", key="direct_api_token"
        )
        source_direct, source_type_direct, hints_direct = _build_metadata_inputs("direct_")
        mode_choice = st.selectbox("Mode", ["text"], key="direct_mode")
        if st.form_submit_button("Ingestion directe"):
            payload_direct = {
                "source": source_direct,
                "source_type": source_type_direct,
                "hints": hints_direct,
            }
            try:
                response_body = _call_ingest_api(
                    api_base_input,
                    api_token_input,
                    INGEST_AUTH_HEADER,
                    payload_direct,
                    mode_choice,
                )
                st.success("Ingestion API réussie")
                st.json(response_body)
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response else "n/a"
                body = exc.response.text if exc.response else ""
                st.error(f"API ingestor a renvoyé {status_code}: {body}")
            except requests.RequestException as exc:
                st.error(f"Erreur réseau API ingestor: {exc}")
            except ValueError as exc:
                st.error(str(exc))


def _render_uploader() -> None:
    st.header("1.b) Uploader un document")
    uploaded = st.file_uploader(
        "Choisissez un fichier (PDF, DOCX, MD)",
        type=["pdf", "docx", "md", "markdown"],
        key="admin_upload_file",
    )
    domain = st.selectbox("Domaine", ["lycee", "web3"], index=0, key="admin_upload_domain")
    title_hint = st.text_input("Titre (optionnel)", "", key="admin_upload_title")
    auto_ingest = st.checkbox("Ingestion immédiate", True, key="admin_upload_auto")

    if uploaded is not None and st.button("Uploader", key="admin_upload_btn"):
        files = {
            "file": (
                uploaded.name,
                uploaded.getvalue(),
                uploaded.type or "application/octet-stream",
            )
        }
        headers: dict[str, str] = {}
        token = INGEST_API_TOKEN
        if token:
            value = token
            if INGEST_AUTH_HEADER.lower() == "authorization" and UI_INGEST_AUTH_BEARER_PREFIX and not token.lower().startswith("bearer "):
                value = f"Bearer {token}"
            headers[INGEST_AUTH_HEADER] = value
        params = {
            "ingest": "true" if auto_ingest else "false",
            "domain": domain,
            "title": title_hint or uploaded.name,
        }
        try:
            base_url = (INGEST_BASE_URL or "").rstrip('/')
            r = requests.post(
                f"{base_url}/admin/upload",
                headers=headers,
                files=files,
                params=params,
                timeout=max(60.0, INGEST_TIMEOUT),
            )
            if r.status_code >= 400:
                st.error(f"Echec upload/ingest: {r.status_code} {r.text}")
            else:
                st.success("Upload réussi")
                st.json(r.json())
        except requests.RequestException as exc:
            st.error(f"Erreur réseau API: {exc}")


def _render_collection_explorer() -> None:
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


def render_app() -> None:
    st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
    st.title("Tableau de bord RAG")
    st.caption("L'interface doit rester derrière un proxy authentifié (Nginx Basic Auth recommandé).")

    st.header("1) Lancer une ingestion")
    _render_admin_form()

    _render_uploader()
    _render_collection_explorer()


if not STREAMLIT_IMPORT_ONLY:
    render_app()
