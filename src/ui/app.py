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

# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"
INGEST_BASE_URL: str = (
    os.getenv("INGEST_API_BASE")
    or os.getenv("INGEST_BASE_URL")
    or "http://ingestor:8001"
)
INGEST_API_TOKEN = os.getenv("INGEST_API_TOKEN") or os.getenv("INGESTOR_API_TOKEN", "")
INGEST_AUTH_HEADER = os.getenv("INGEST_AUTH_HEADER", os.getenv("UI_INGEST_AUTH_HEADER", "Authorization"))
UI_INGEST_AUTH_BEARER_PREFIX = (
    os.getenv("UI_INGEST_AUTH_BEARER_PREFIX", "true").strip().lower() in {"1", "true", "yes"}
)
INGEST_TIMEOUT = float(os.getenv("UI_INGEST_TIMEOUT", os.getenv("UI_WEBHOOK_TIMEOUT", "30")))
CHROMA_TIMEOUT = float(os.getenv("CHROMA_REQUEST_TIMEOUT", os.getenv("UI_CHROMA_TIMEOUT", "30")))
UI_MAX_K = max(1, int(os.getenv("UI_MAX_K", "8")))
UI_DEFAULT_K = min(max(int(os.getenv("UI_DEFAULT_K", "4")), 1), UI_MAX_K)
STREAMLIT_IMPORT_ONLY = os.getenv("STREAMLIT_IMPORT_ONLY", "0") == "1"

# Options d'ingestion
SOURCE_TYPE_LABELS: dict[str, str] = {
    "url": "URL unique",
    "url_list": "Liste d'URLs",
    "gdrive_folder": "Dossier Google Drive",
    "upload": "Upload de fichiers",
}

# Types de fichiers supportés
ALLOWED_EXTENSIONS = ["pdf", "docx", "md", "markdown", "txt"]

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _build_metadata_inputs(prefix: str) -> dict[str, Any]:
    """Build metadata input fields for ingestion."""
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
    return {
        "matiere": matiere,
        "voie": voie,
        "niveau": niveau,
        "document_type": doc_type,
        "annee_programme": annee,
    }


def _get_auth_headers(token: str | None) -> dict[str, str]:
    """Build authentication headers for API calls."""
    headers = {}
    if token:
        value = token
        if INGEST_AUTH_HEADER.lower() == "authorization" and UI_INGEST_AUTH_BEARER_PREFIX:
            if not token.lower().startswith("bearer "):
                value = f"Bearer {token}"
        headers[INGEST_AUTH_HEADER] = value
    return headers


@st.cache_resource(show_spinner=False)
def _chromadb_collection():
    """Get or create ChromaDB collection with caching."""
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
    """Get collection document count with caching."""
    from typing import cast
    return cast(int, _chromadb_collection().count())


def _query_chroma(collection, query_text: str, n_results: int):
    """Query ChromaDB for similar documents."""
    return collection.query(query_texts=[query_text], n_results=n_results)


def _call_ingest_api(
    base_url: str,
    token: str | None,
    payload: dict[str, Any],
    mode: str = "text",
    timeout: float | None = None,
) -> dict[str, Any]:
    """Call the ingest API endpoint."""
    if not base_url:
        raise ValueError("Adresse de l'API d'ingestion absente")
    url = f"{base_url.rstrip('/')}/ingest"
    headers = {"Content-Type": "application/json"}
    headers.update(_get_auth_headers(token))
    response = requests.post(
        url,
        params={"mode": mode},
        json=payload,
        headers=headers,
        timeout=timeout or INGEST_TIMEOUT,
    )
    response.raise_for_status()
    from typing import cast
    return cast(dict[str, Any], response.json())


# ═══════════════════════════════════════════════════════════════════
# Ingestion Forms
# ═══════════════════════════════════════════════════════════════════


def _render_single_url_form() -> None:
    """Render single URL ingestion form."""
    st.subheader("📄 Ingestion d'une URL unique")
    st.caption("Ingérez une page web ou un document PDF en ligne")

    with st.form("single_url_form"):
        url = st.text_input(
            "URL du document",
            placeholder="https://eduscol.education.fr/...",
            key="single_url_input",
        )
        hints = _build_metadata_inputs("single_url")
        mode = st.selectbox("Mode", ["text", "multimodal"], index=0, key="single_url_mode")

        submitted = st.form_submit_button("🚀 Lancer l'ingestion", use_container_width=True)

        if submitted:
            if not url:
                st.error("Veuillez saisir une URL")
            else:
                payload = {
                    "source_type": "url",
                    "source": url,
                    "hints": hints,
                }
                try:
                    with st.spinner("Ingestion en cours..."):
                        result = _call_ingest_api(
                            INGEST_BASE_URL,
                            INGEST_API_TOKEN,
                            payload,
                            mode,
                            timeout=60,
                        )
                    st.success(f"✅ Ingestion réussie : {result.get('added', 0)} chunks ajoutés")
                    st.json(result)
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response else "n/a"
                    body = exc.response.text if exc.response else ""
                    st.error(f"❌ Erreur API ({status_code}) : {body}")
                except requests.RequestException as exc:
                    st.error(f"❌ Erreur réseau : {exc}")
                except ValueError as exc:
                    st.error(f"❌ Erreur : {exc}")


def _render_multi_url_form() -> None:
    """Render multi-URL ingestion form."""
    st.subheader("🔗 Ingestion multiple d'URLs")
    st.caption("Ingérez plusieurs URLs en une seule fois (une par ligne)")

    with st.form("multi_url_form"):
        urls_text = st.text_area(
            "Liste des URLs",
            placeholder="https://example.com/page1\nhttps://example.com/page2\nhttps://example.com/page3",
            key="multi_urls_input",
            help="Saisissez une URL par ligne",
        )
        hints = _build_metadata_inputs("multi_url")
        mode = st.selectbox("Mode", ["text", "multimodal"], index=0, key="multi_url_mode")
        _ = st.checkbox(
            "Traitement parallèle",
            value=False,
            key="multi_url_parallel",
            help="Traiter les URLs en parallèle (expérimental)",
        )

        submitted = st.form_submit_button("🚀 Lancer l'ingestion multiple", use_container_width=True)

        if submitted:
            if not urls_text:
                st.error("Veuillez saisir au moins une URL")
            else:
                urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
                if not urls:
                    st.error("Aucune URL valide trouvée")
                else:
                    st.info(f"📋 {len(urls)} URLs à ingérer")
                    results = []
                    errors = []
                    progress_bar = st.progress(0)

                    for i, url in enumerate(urls):
                        payload = {
                            "source_type": "url",
                            "source": url,
                            "hints": hints,
                        }
                        try:
                            result = _call_ingest_api(
                                INGEST_BASE_URL,
                                INGEST_API_TOKEN,
                                payload,
                                mode,
                                timeout=120,
                            )
                            results.append({"url": url, "status": "success", "result": result})
                        except Exception as exc:
                            errors.append({"url": url, "error": str(exc)})
                            results.append({"url": url, "status": "error", "error": str(exc)})

                        progress_bar.progress((i + 1) / len(urls))

                    # Display results
                    st.subheader("📊 Résultats")
                    success_count = len([r for r in results if r["status"] == "success"])
                    error_count = len(errors)
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Succès", success_count)
                    with col2:
                        st.metric("Échecs", error_count)

                    if errors:
                        with st.expander(f"⚠️ Voir les {error_count} erreurs"):
                            for err in errors:
                                st.error(f"**{err['url']}** : {err['error']}")

                    if results:
                        with st.expander("📄 Détails des résultats"):
                            st.json(results)


def _render_gdrive_form() -> None:
    """Render Google Drive ingestion form."""
    st.subheader("📁 Ingestion depuis Google Drive")
    st.caption("Ingérez tous les documents d'un dossier Google Drive")

    st.info(
        "⚠️ **Configuration requise :**\n"
        "- Un compte de service Google Cloud doit être configuré\n"
        "- Le dossier doit être partagé avec le compte de service\n"
        "- Voir la documentation pour la configuration",
        icon="ℹ️",
    )

    with st.form("gdrive_form"):
        col1, col2 = st.columns(2)
        with col1:
            folder_id = st.text_input(
                "ID du dossier Google Drive",
                placeholder="1xABCDEFGH123456789",
                key="gdrive_folder_id",
                help="L'ID du dossier se trouve dans l'URL de Google Drive",
            )
        with col2:
            _ = st.number_input(
                "Nombre max de documents",
                min_value=1,
                max_value=1000,
                value=200,
                key="gdrive_max_docs",
            )

        _ = st.checkbox("Inclure les sous-dossiers", value=True, key="gdrive_recursive")
        hints = _build_metadata_inputs("gdrive")

        submitted = st.form_submit_button("🚀 Lancer l'ingestion Google Drive", use_container_width=True)

        if submitted:
            if not folder_id:
                st.error("Veuillez saisir l'ID du dossier Google Drive")
            else:
                payload = {
                    "source_type": "gdrive_folder",
                    "source": folder_id,
                    "hints": hints,
                }
                try:
                    with st.spinner(
                        "Ingestion Google Drive en cours (cela peut prendre plusieurs minutes)..."
                    ):
                        result = _call_ingest_api(
                            INGEST_BASE_URL,
                            INGEST_API_TOKEN,
                            payload,
                            "text",
                            timeout=300,  # 5 minutes timeout
                        )
                    st.success(f"✅ Ingestion réussie : {result.get('added', 0)} chunks ajoutés")
                    st.json(result)
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response else "n/a"
                    body = exc.response.text if exc.response else ""
                    st.error(f"❌ Erreur API ({status_code}) : {body}")
                    if status_code == 500:
                        st.warning(
                            "⚠️ Vérifiez que les credentials Google Drive sont configurés correctement"
                        )
                except requests.RequestException as exc:
                    st.error(f"❌ Erreur réseau : {exc}")
                except ValueError as exc:
                    st.error(f"❌ Erreur : {exc}")


def _render_multi_upload_form() -> None:
    """Render multi-file upload form."""
    st.subheader("📤 Upload de fichiers multiples")
    st.caption("Téléchargez et ingérez plusieurs fichiers en une seule fois")

    uploaded_files = st.file_uploader(
        "Choisissez des fichiers",
        type=ALLOWED_EXTENSIONS,
        accept_multiple_files=True,
        key="multi_upload_files",
        help="PDF, DOCX, Markdown, TXT supportés",
    )

    if uploaded_files:
        st.info(f"📋 {len(uploaded_files)} fichier(s) sélectionné(s)")

        # Display file list
        with st.expander("📄 Voir la liste des fichiers"):
            file_data = []
            for f in uploaded_files:
                file_data.append(
                    {
                        "Nom": f.name,
                        "Type": f.type,
                        "Taille": f"{f.size / 1024:.1f} KB",
                    }
                )
            st.dataframe(file_data, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        domain = st.selectbox("Domaine", ["lycee", "web3"], index=0, key="upload_domain")
    with col2:
        auto_ingest = st.checkbox("Ingestion immédiate", value=True, key="upload_auto_ingest")

    if uploaded_files and st.button(
        "🚀 Uploader et ingérer", use_container_width=True, key="multi_upload_btn"
    ):
        if not auto_ingest:
            # Just upload without ingestion
            results = []
            for uploaded in uploaded_files:
                try:
                    files = {
                        "file": (
                            uploaded.name,
                            uploaded.getvalue(),
                            uploaded.type or "application/octet-stream",
                        )
                    }
                    headers = _get_auth_headers(INGEST_API_TOKEN)
                    base_url = (INGEST_BASE_URL or "").rstrip("/")
                    r = requests.post(
                        f"{base_url}/admin/upload",
                        headers=headers,
                        files=files,
                        params={"ingest": "false", "domain": domain, "title": uploaded.name},
                        timeout=max(60.0, INGEST_TIMEOUT),
                    )
                    if r.status_code >= 400:
                        results.append(
                            {"file": uploaded.name, "status": "error", "error": r.text}
                        )
                    else:
                        results.append({"file": uploaded.name, "status": "success", "result": r.json()})
                except Exception as exc:
                    results.append({"file": uploaded.name, "status": "error", "error": str(exc)})

            st.success("Upload terminé")
            st.json(results)
        else:
            # Upload and ingest
            progress_bar = st.progress(0)
            results = []
            errors = []

            for i, uploaded in enumerate(uploaded_files):
                try:
                    # Upload file
                    files = {
                        "file": (
                            uploaded.name,
                            uploaded.getvalue(),
                            uploaded.type or "application/octet-stream",
                        )
                    }
                    headers = _get_auth_headers(INGEST_API_TOKEN)
                    base_url = (INGEST_BASE_URL or "").rstrip("/")

                    # First upload
                    r = requests.post(
                        f"{base_url}/admin/upload",
                        headers=headers,
                        files=files,
                        params={
                            "ingest": "true",
                            "domain": domain,
                            "title": uploaded.name,
                        },
                        timeout=max(120.0, INGEST_TIMEOUT),
                    )

                    if r.status_code >= 400:
                        errors.append({"file": uploaded.name, "error": r.text})
                        results.append({"file": uploaded.name, "status": "error", "error": r.text})
                    else:
                        result_data = r.json()
                        results.append({"file": uploaded.name, "status": "success", "result": result_data})

                except Exception as exc:
                    errors.append({"file": uploaded.name, "error": str(exc)})
                    results.append({"file": uploaded.name, "status": "error", "error": str(exc)})

                progress_bar.progress((i + 1) / len(uploaded_files))

            # Display results
            st.subheader("📊 Résultats")
            success_count = len([r for r in results if r["status"] == "success"])
            error_count = len(errors)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Succès", success_count)
            with col2:
                st.metric("Échecs", error_count)

            if errors:
                with st.expander(f"⚠️ Voir les {error_count} erreurs"):
                    for err in errors:
                        st.error(f"**{err['file']}** : {err['error']}")

            if results:
                with st.expander("📄 Détails des résultats"):
                    st.json(results)


# ═══════════════════════════════════════════════════════════════════
# Collection Explorer
# ═══════════════════════════════════════════════════════════════════


def _render_collection_explorer() -> None:
    """Render ChromaDB collection explorer."""
    st.header("🔍 Explorer la base de connaissances")

    try:
        col = _chromadb_collection()
        count = _collection_count()
        st.info(f"📚 Collection '{COLLECTION}' – **{count}** documents")

        # Search form
        with st.form("search_form"):
            cols = st.columns(3)
            with cols[0]:
                query = st.text_input("Requête", "définition de la dérivée (Terminale)")
            with cols[1]:
                k = st.slider("Résultats", 1, UI_MAX_K, UI_DEFAULT_K)
            with cols[2]:
                submitted = st.form_submit_button("🔍 Rechercher", use_container_width=True)

        if submitted:
            with st.spinner("Recherche en cours..."):
                res = _query_chroma(col, query, k)

            documents: Sequence[Sequence[str]] | None = res.get("documents")
            metadatas: Sequence[Sequence[Mapping[str, Any]]] | None = res.get("metadatas")
            distances: Sequence[Sequence[float]] | None = res.get("distances")

            if not documents or not metadatas or not distances:
                st.warning("Aucun résultat trouvé.")
            else:
                first_docs = documents[0]
                first_metas = metadatas[0]
                first_distances = distances[0]

                for i, doc in enumerate(first_docs):
                    distance = (
                        first_distances[i] if i < len(first_distances) else float("nan")
                    )
                    metadata = first_metas[i] if i < len(first_metas) else {}

                    with st.expander(
                        f"📄 Résultat #{i + 1} — distance {distance:.4f}"
                    ):
                        st.text_area("Extrait", doc, height=150, key=f"doc_{i}")

                        # Display metadata as table
                        if metadata:
                            df = pd.DataFrame(
                                list(metadata.items()), columns=["Champ", "Valeur"]
                            )
                            st.dataframe(df, use_container_width=True)

    except (chroma_errors.ChromaError, requests.RequestException, ValueError) as exc:
        st.error(f"❌ Chroma indisponible : {exc}")


# ═══════════════════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════════════════


def render_app() -> None:
    """Render the main Streamlit application."""
    st.set_page_config(
        layout="wide",
        page_title="RAG Local - Ingestion",
        page_icon="📚",
    )

    # Header
    st.title("📚 RAG Local - Tableau de bord d'ingestion")
    st.caption(
        "Interface d'ingestion de documents pour la base de connaissances RAG. "
        "⚠️ Cette interface doit être protégée par Nginx Basic Auth."
    )

    # Stats banner
    try:
        count = _collection_count()
        st.metric("📊 Documents dans la base", count, label_visibility="collapsed")
    except Exception:
        st.warning("Impossible de récupérer le nombre de documents")

    st.divider()

    # Ingestion tabs
    st.header("1️⃣ Nouvelles ingestions")

    tab_single, tab_multi, tab_gdrive, tab_upload = st.tabs(
        [
            "📄 URL unique",
            "🔗 URLs multiples",
            "📁 Google Drive",
            "📤 Upload de fichiers",
        ]
    )

    with tab_single:
        _render_single_url_form()

    with tab_multi:
        _render_multi_url_form()

    with tab_gdrive:
        _render_gdrive_form()

    with tab_upload:
        _render_multi_upload_form()

    st.divider()

    # Collection explorer
    st.header("2️⃣ Explorer la base")
    _render_collection_explorer()

    # Footer
    st.divider()
    st.caption(
        "RAG Local v2.0 | "
        f"API: {INGEST_BASE_URL} | "
        "Documentation: `docs/README.md`"
    )


if not STREAMLIT_IMPORT_ONLY:
    render_app()
