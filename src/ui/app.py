import os
from collections.abc import Mapping, Sequence
from typing import Any, cast
from urllib.parse import quote_plus

import chromadb
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from chromadb import errors as chroma_errors
from chromadb.config import Settings

CHROMA_HOST = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
COLLECTION = "ressources_pedagogiques_terminale"
N8N_DEFAULT_WEBHOOK = os.getenv("N8N_DEFAULT_WEBHOOK", "")
WEBHOOK_TIMEOUT = float(os.getenv("UI_WEBHOOK_TIMEOUT", "10"))
INGEST_BASE_URL = os.getenv("INGEST_API_BASE") or os.getenv("INGEST_BASE_URL", "http://ingestor:8001")
INGEST_API_TOKEN = os.getenv("INGEST_API_TOKEN") or os.getenv("INGESTOR_API_TOKEN", "")
INGEST_AUTH_HEADER = os.getenv("INGEST_AUTH_HEADER", "X-API-Token")
INGEST_TIMEOUT = float(os.getenv("UI_INGEST_TIMEOUT", os.getenv("UI_WEBHOOK_TIMEOUT", "10")))
CHROMA_TIMEOUT = float(os.getenv("CHROMA_REQUEST_TIMEOUT", os.getenv("UI_CHROMA_TIMEOUT", "30")))
UI_MAX_K = max(1, int(os.getenv("UI_MAX_K", "8")))
UI_DEFAULT_K = min(max(int(os.getenv("UI_DEFAULT_K", "4")), 1), UI_MAX_K)
STREAMLIT_IMPORT_ONLY = os.getenv("STREAMLIT_IMPORT_ONLY", "0") == "1"
ADMIN_BASE_URL = os.getenv("ADMIN_API_BASE") or INGEST_BASE_URL
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", INGEST_API_TOKEN)
ADMIN_AUTH_HEADER = os.getenv("ADMIN_AUTH_HEADER", "X-API-Key")
ADMIN_TIMEOUT = float(os.getenv("ADMIN_REQUEST_TIMEOUT", "10"))
ADMIN_SSE_TOKEN_PARAM = os.getenv("ADMIN_SSE_TOKEN_PARAM")
TENANT_OPTIONS = [slug.strip() for slug in os.getenv("TENANTS", "edu,web3").split(",") if slug.strip()]
if not TENANT_OPTIONS:
    TENANT_OPTIONS = ["edu", "web3"]

SOURCE_TYPE_LABELS: dict[str, str] = {
    "url": "URL / Page web",
    "gdrive_folder": "Dossier Google Drive",
    "pdf": "PDF local",
    "docx": "Document Word (.docx)",
    "markdown": "Markdown (.md)",
    "video": "Vidéo (mp4, YouTube, etc.)",
}
SOURCE_PLACEHOLDERS: dict[str, str] = {
    "url": "https://eduscol.education.fr/...",
    "gdrive_folder": "1xABCDEFGH123456789",
    "pdf": "/data/uploads/ressource.pdf",
    "docx": "/data/uploads/ressource.docx",
    "markdown": "/data/uploads/ressource.md",
    "video": "/data/uploads/cours.mp4",
}
MULTIMODAL_ONLY_TYPES = {"video"}


def _build_metadata_inputs(prefix: str) -> tuple[str, str, dict[str, Any]]:
    options = list(SOURCE_TYPE_LABELS.keys())
    source_type: str = st.selectbox(
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
        annee_raw = st.number_input(
            "Année", min_value=2010, max_value=2035, value=2024, key=f"{prefix}annee"
        )
    hints: dict[str, Any] = {
        "matiere": matiere,
        "voie": voie,
        "niveau": niveau,
        "document_type": doc_type,
        "annee_programme": int(annee_raw),
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


def _call_webhook(url: str, body: dict[str, Any]) -> requests.Response:
    response = requests.post(url, json=body, timeout=WEBHOOK_TIMEOUT)
    response.raise_for_status()
    return response


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
        headers[header_name] = token
    response = requests.post(url, params={"mode": mode}, json=payload, headers=headers, timeout=INGEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _admin_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if ADMIN_API_KEY:
        headers[ADMIN_AUTH_HEADER] = ADMIN_API_KEY
        if ADMIN_AUTH_HEADER.lower() != "x-api-key":
            headers.setdefault("X-API-Key", ADMIN_API_KEY)
    return headers


def _call_admin_api(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not ADMIN_BASE_URL:
        raise ValueError("ADMIN_API_BASE absent")
    url = f"{ADMIN_BASE_URL.rstrip('/')}{path}"
    response = requests.request(
        method,
        url,
        headers=_admin_headers(),
        json=payload,
        params=params,
        timeout=ADMIN_TIMEOUT,
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


@st.cache_data(ttl=15, show_spinner=False)
def _admin_list_folders(tenant: str) -> list[dict[str, Any]]:
    body = _call_admin_api("GET", "/admin/folders", params={"tenant": tenant})
    return cast(list[dict[str, Any]], body.get("folders", []))


@st.cache_data(ttl=15, show_spinner=False)
def _admin_taxonomy(tenant: str) -> dict[str, list[str]]:
    body = _call_admin_api("GET", "/admin/taxonomy", params={"tenant": tenant})
    return cast(dict[str, list[str]], body.get("facets", {}))


@st.cache_data(ttl=10, show_spinner=False)
def _admin_jobs(tenant: str) -> list[dict[str, Any]]:
    body = _call_admin_api("GET", "/admin/jobs", params={"tenant": tenant, "limit": 50})
    return cast(list[dict[str, Any]], body.get("jobs", []))


def _clear_cached(fn: Any) -> None:
    clear_fn = getattr(fn, "clear", None)
    if callable(clear_fn):
        clear_fn()


def _render_ingestion_form() -> None:
    st.subheader("Ingestion orchestrée via n8n")
    webhook_default = N8N_DEFAULT_WEBHOOK or "https://EXEMPLE.webhook.url/ingestion"
    webhook = st.text_input("URL Webhook n8n (production)", webhook_default)
    with st.form("ingest"):
        source, source_type, hints = _build_metadata_inputs("webhook_")
        if st.form_submit_button("Envoyer"):
            if not webhook.startswith("http"):
                st.error("URL webhook invalide")
            else:
                payload = {
                    "source": source,
                    "source_type": source_type,
                    "hints": hints,
                }
                try:
                    _call_webhook(webhook, payload)
                    st.success("Webhook accepté par n8n (voir journaux n8n pour le détail)")
                except requests.HTTPError as exc:
                    st.error(f"n8n a renvoyé {exc.response.status_code}: vérifier le workflow")
                except requests.RequestException as exc:
                    st.error(f"Erreur réseau webhook: {exc}")


def _render_direct_ingest_form() -> None:
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
        mode_choice = st.selectbox("Mode", ["text", "multimodal"], key="direct_mode")
        if source_type_direct in MULTIMODAL_ONLY_TYPES and mode_choice != "multimodal":
            st.warning("Sélectionnez le mode 'multimodal' pour traiter une vidéo.")
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


def _render_oneclick_form() -> None:
    st.subheader("Ingestion 1-clic (multi-tenant)")
    tenant = st.selectbox("Tenant", TENANT_OPTIONS, key="oneclick_tenant")
    folder_path = st.text_input("Dossier cible", "guides/nouveau", key="oneclick_folder")
    source_type = st.selectbox(
        "Type de source",
        [
            "url",
            "gdrive",
            "gdrive_folder",
            "file",
            "html",
            "markdown",
            "pdf",
            "docx",
            "md",
            "video",
        ],
        key="oneclick_source_type",
    )
    source_value = st.text_input("Valeur source", "https://exemple.com", key="oneclick_source_value")
    mode = st.selectbox("Mode", ["text", "multimodal"], key="oneclick_mode")
    taxonomy_values = _admin_taxonomy(tenant)

    with st.form("oneclick_form"):
        selected_taxonomy: dict[str, str] = {}
        for facet, values in sorted(taxonomy_values.items()):
            default_value = values[0] if values else ""
            selected_taxonomy[facet] = st.text_input(
                f"Taxonomie – {facet}",
                value=default_value,
                key=f"oneclick_tax_{facet}",
            )
        idempotency = st.text_input("Idempotency key (optionnel)", "", key="oneclick_idempotency")
        submit = st.form_submit_button("Lancer l'ingestion 1-clic")
        if submit:
            payload = {
                "tenant": tenant,
                "folder_path": folder_path,
                "source_type": source_type,
                "source_value": source_value,
                "taxonomy": {k: v for k, v in selected_taxonomy.items() if v},
                "mode": mode,
                "idempotency_key": idempotency or None,
            }
            try:
                response = _call_admin_api("POST", "/admin/ingest/oneclick", payload=payload)
                st.success(f"Job {response['jobId']} terminé")
                st.json(response)
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response else "n/a"
                detail = exc.response.text if exc.response else str(exc)
                st.error(f"Erreur {status_code} lors de l'ingestion 1-clic: {detail}")
            except requests.RequestException as exc:
                st.error(f"Erreur réseau ingestion 1-clic: {exc}")


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
                        df_metadata = pd.DataFrame(
                            list(metadata.items()),
                            columns=pd.Index(["Champ", "Valeur"]),
                        )
                        st.dataframe(df_metadata)
    except (chroma_errors.ChromaError, requests.RequestException, ValueError) as exc:
        st.error(f"Chroma indisponible: {exc}")


def _sse_url(job_id: str, tenant: str) -> str:
    base = ADMIN_BASE_URL.rstrip("/") if ADMIN_BASE_URL else ""
    url = f"{base}/admin/jobs/{job_id}/events?tenant={tenant}"
    if ADMIN_SSE_TOKEN_PARAM and ADMIN_API_KEY:
        token_param = ADMIN_SSE_TOKEN_PARAM.strip()
        if token_param:
            url = f"{url}&{token_param}={quote_plus(ADMIN_API_KEY)}"
    return url


def _render_jobs_dashboard() -> None:
        st.subheader("Jobs & suivi en direct")
        tenant = st.selectbox("Tenant", TENANT_OPTIONS, key="jobs_tenant")
        if st.button("Rafraîchir les jobs", key="jobs_refresh"):
            _clear_cached(_admin_jobs)

        jobs = _admin_jobs(tenant)
        job_table = pd.DataFrame(jobs) if jobs else pd.DataFrame(columns=pd.Index(["id", "status", "collection"]))
        st.dataframe(job_table)

        selected_job = st.selectbox(
                "Job à suivre",
                [job.get("id") for job in jobs] if jobs else [""],
                index=0,
                key="jobs_selected",
        )
        if selected_job:
                st.markdown("**📡 Suivi SSE**")
                url = _sse_url(selected_job, tenant)
                html = f"""
<div id=\"sse-container\" style=\"height:240px; overflow:auto; border:1px solid #ddd; padding:8px; font-family:monospace; background:#0f172a; color:#f8fafc;\"></div>
<script>
const target = document.getElementById("sse-container");
const source = new EventSource("{url}");
const append = (text) => {{
    const line = document.createElement("div");
    line.textContent = text;
    target.appendChild(line);
    target.scrollTop = target.scrollHeight;
}};
source.addEventListener("message", (event) => {{
    try {{
        const data = JSON.parse(event.data);
        append(`[${{data.timestamp || ""}}] [${{data.level}}] ${{data.message}}`);
    }} catch (err) {{
        append(`(parse error) ${{event.data}}`);
    }}
}});
source.addEventListener("keepalive", () => {{
    append("⋯ keepalive");
}});
source.onerror = () => {{
    append("❌ connexion SSE interrompue");
}};
</script>
"""
                components.html(html, height=260)


def _render_folder_taxonomy_manager() -> None:
    st.subheader("Dossiers & Taxonomie")
    tenant = st.selectbox("Tenant", TENANT_OPTIONS, key="manager_tenant")
    if st.button("Rafraîchir les données", key="refresh_manager"):
        _clear_cached(_admin_list_folders)
        _clear_cached(_admin_taxonomy)

    folders = _admin_list_folders(tenant)
    if folders:
        df_folders = pd.DataFrame(folders)
        st.dataframe(df_folders)
    else:
        st.info("Aucun dossier enregistré pour ce tenant")

    with st.form("create_folder_form"):
        st.markdown("**Créer un dossier**")
        folder_path = st.text_input("Chemin complet", "guides/exemple", key="create_folder_path")
        folder_slug = st.text_input("Slug (optionnel)", "", key="create_folder_slug")
        create = st.form_submit_button("Créer le dossier")
        if create:
            payload = {"tenant": tenant, "path": folder_path, "slug": folder_slug or None}
            try:
                response = _call_admin_api("POST", "/admin/folders", payload=payload)
                st.success(f"Dossier '{response['folder']['path']}' créé")
                _clear_cached(_admin_list_folders)
            except requests.HTTPError as exc:
                detail = exc.response.text if exc.response else str(exc)
                st.error(f"Erreur de création de dossier: {detail}")
            except requests.RequestException as exc:
                st.error(f"Erreur réseau dossier: {exc}")

    taxonomy = _admin_taxonomy(tenant)
    if taxonomy:
        st.markdown("**Taxonomie actuelle**")
        st.json(taxonomy)

    with st.form("add_taxonomy_form"):
        st.markdown("**Ajouter une valeur de taxonomie**")
        facet = st.text_input("Facet", "doc_type", key="taxonomy_facet")
        value = st.text_input("Valeur", "cours", key="taxonomy_value")
        submit = st.form_submit_button("Ajouter la valeur")
        if submit:
            payload = {"tenant": tenant, "facet": facet, "value": value}
            try:
                response = _call_admin_api("POST", "/admin/taxonomy", payload=payload)
                st.success(f"Valeur '{response['value']}' ajoutée à '{response['facet']}'")
                _clear_cached(_admin_taxonomy)
            except requests.HTTPError as exc:
                detail = exc.response.text if exc.response else str(exc)
                st.error(f"Erreur taxonomie: {detail}")
            except requests.RequestException as exc:
                st.error(f"Erreur réseau taxonomie: {exc}")


def render_app() -> None:
    st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
    st.title("Tableau de bord RAG")
    st.caption("L'interface doit rester derrière un proxy authentifié (Nginx Basic Auth recommandé).")
    tabs = st.tabs([
        "Ingestion",
        "Dossiers & Taxonomie",
        "Jobs",
        "Collections & Recherche",
    ])

    with tabs[0]:
        _render_ingestion_form()
        st.divider()
        _render_direct_ingest_form()
        st.divider()
        _render_oneclick_form()

    with tabs[1]:
        _render_folder_taxonomy_manager()

    with tabs[2]:
        _render_jobs_dashboard()

    with tabs[3]:
        _render_collection_explorer()


if not STREAMLIT_IMPORT_ONLY:
    render_app()
