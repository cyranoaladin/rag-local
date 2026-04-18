import json
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

try:
    import plotly.graph_objects as go  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — plotly is optional in dev
    go = None  # type: ignore[assignment]

# --- Configuration ---
INGEST_BASE_URL = os.getenv("INGEST_API_BASE") or os.getenv("INGEST_BASE_URL", "http://ingestor:8001")
INGEST_API_TOKEN = os.getenv("INGEST_API_TOKEN") or os.getenv("INGESTOR_API_TOKEN", "")
N8N_DEFAULT_WEBHOOK = os.getenv("N8N_DEFAULT_WEBHOOK", "")
WEBHOOK_TIMEOUT = float(os.getenv("UI_WEBHOOK_TIMEOUT", "10"))
INGEST_TIMEOUT = float(os.getenv("UI_INGEST_TIMEOUT", "1800"))
SEARCH_TIMEOUT = float(os.getenv("UI_SEARCH_TIMEOUT", "30"))
UI_MAX_K = max(1, int(os.getenv("UI_MAX_K", "20")))
UI_DEFAULT_K = min(max(int(os.getenv("UI_DEFAULT_K", "6")), 1), UI_MAX_K)
STREAMLIT_IMPORT_ONLY = os.getenv("STREAMLIT_IMPORT_ONLY", "0") == "1"
UI_DEFAULT_COLLECTION = os.getenv("UI_DEFAULT_COLLECTION", "rag_francais_premiere")
UI_DEFAULT_MATIERE = os.getenv("UI_DEFAULT_MATIERE", "Français")
UI_KNOWN_COLLECTIONS = [
    UI_DEFAULT_COLLECTION,
    "rag_education",
    "rag_web3",
]

ACCEPTED_FILE_TYPES = [
    "pdf", "md", "txt", "docx", "csv", "json", "xml", "html",
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp",
    "mp3", "wav", "ogg", "flac", "m4a", "aac", "wma",
    "mp4", "webm", "mkv", "mov", "avi",
]

SOURCE_TYPE_MAP: dict[str, dict[str, str]] = {
    "url": {"label": "URL / Page web", "icon": "🌐", "placeholder": "https://eduscol.education.fr/..."},
    "gdrive_folder": {"label": "Dossier Google Drive", "icon": "📁", "placeholder": "1xABCDEFGH123456789"},
    "pdf": {"label": "PDF local", "icon": "📄", "placeholder": "/data/uploads/ressource.pdf"},
    "docx": {"label": "Document Word (.docx)", "icon": "📝", "placeholder": "/data/uploads/ressource.docx"},
    "markdown": {"label": "Markdown (.md)", "icon": "📋", "placeholder": "/data/uploads/ressource.md"},
    "video": {"label": "Video / Audio", "icon": "🎬", "placeholder": "/data/uploads/cours.mp4"},
}
MULTIMODAL_ONLY_TYPES = {"video"}

FILE_TYPE_ICONS: dict[str, str] = {
    "pdf": "📄", "md": "📋", "txt": "📝", "docx": "📝", "csv": "📊",
    "json": "🔧", "xml": "🔧", "html": "🌐",
    "jpg": "🖼️", "jpeg": "🖼️", "png": "🖼️", "gif": "🖼️",
    "mp3": "🎵", "wav": "🎵", "ogg": "🎵", "flac": "🎵",
    "mp4": "🎬", "webm": "🎬", "mkv": "🎬", "mov": "🎬", "avi": "🎬",
}

NAV_ITEMS: list[dict[str, str]] = [
    {"key": "dashboard", "icon": "📊", "label": "Tableau de bord"},
    {"key": "ingestion", "icon": "📥", "label": "Ingestion"},
    {"key": "search", "icon": "🔍", "label": "Recherche"},
    {"key": "explore", "icon": "📚", "label": "Exploration"},
    {"key": "admin", "icon": "⚙️", "label": "Administration"},
]


# --- Custom CSS ---

_CUSTOM_CSS = """
<style>
    /* Global */
    .block-container { padding-top: 1.5rem; }
    section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }

    /* KPI Cards */
    .kpi-card {
        background: linear-gradient(135deg, #1E293B 0%, #334155 100%);
        border: 1px solid #475569;
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        margin-bottom: 0.8rem;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(79, 70, 229, 0.15);
    }
    .kpi-value {
        font-size: 2rem;
        font-weight: 700;
        color: #A5B4FC;
        line-height: 1.2;
    }
    .kpi-label {
        font-size: 0.85rem;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 0.3rem;
    }
    .kpi-icon { font-size: 1.4rem; margin-bottom: 0.4rem; }

    /* Status badge */
    .status-online {
        display: inline-flex; align-items: center; gap: 0.4rem;
        background: #065F46; color: #6EE7B7; padding: 0.3rem 0.8rem;
        border-radius: 9999px; font-size: 0.8rem; font-weight: 600;
    }
    .status-offline {
        display: inline-flex; align-items: center; gap: 0.4rem;
        background: #7F1D1D; color: #FCA5A5; padding: 0.3rem 0.8rem;
        border-radius: 9999px; font-size: 0.8rem; font-weight: 600;
    }

    /* Score bar */
    .score-bar-container {
        background: #1E293B;
        border-radius: 8px;
        overflow: hidden;
        height: 8px;
        margin-top: 4px;
    }
    .score-bar-fill {
        height: 100%;
        border-radius: 8px;
        transition: width 0.5s ease;
    }

    /* Result card */
    .result-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
        border-left: 4px solid #4F46E5;
    }
    .result-rank {
        font-size: 0.75rem;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .result-score {
        font-size: 1.1rem;
        font-weight: 700;
        color: #A5B4FC;
    }
    .result-meta-tag {
        display: inline-block;
        background: #334155;
        color: #CBD5E1;
        padding: 0.15rem 0.5rem;
        border-radius: 6px;
        font-size: 0.75rem;
        margin: 0.15rem 0.15rem 0.15rem 0;
    }

    /* Ingest result */
    .ingest-ok {
        background: #064E3B; border: 1px solid #059669;
        border-radius: 8px; padding: 0.8rem 1rem; margin: 0.4rem 0;
    }
    .ingest-err {
        background: #7F1D1D; border: 1px solid #DC2626;
        border-radius: 8px; padding: 0.8rem 1rem; margin: 0.4rem 0;
    }

    /* File chip */
    .file-chip {
        display: inline-flex; align-items: center; gap: 0.3rem;
        background: #334155; color: #E2E8F0;
        padding: 0.3rem 0.7rem; border-radius: 8px;
        font-size: 0.82rem; margin: 0.2rem;
    }

    /* Sidebar branding */
    .sidebar-brand {
        text-align: center;
        padding: 0.5rem 0 1rem 0;
        border-bottom: 1px solid #334155;
        margin-bottom: 1rem;
    }
    .sidebar-brand h2 {
        font-size: 1.3rem;
        background: linear-gradient(135deg, #818CF8, #6366F1);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }
    .sidebar-brand p {
        color: #94A3B8; font-size: 0.75rem; margin: 0.2rem 0 0 0;
    }

    /* Exploration doc card */
    .doc-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.6rem;
    }
    .doc-card-title {
        font-weight: 600;
        color: #E2E8F0;
        font-size: 0.95rem;
    }
    .doc-card-meta {
        color: #94A3B8;
        font-size: 0.8rem;
        margin-top: 0.3rem;
    }
</style>
"""


# --- API Helpers ---

def _api_headers() -> dict[str, str]:
    """Build auth headers for API calls."""
    headers: dict[str, str] = {}
    if INGEST_API_TOKEN:
        headers["X-API-Token"] = INGEST_API_TOKEN
    return headers


def api_get(path: str, timeout: float = 30.0) -> dict[str, Any]:
    """GET request to the ingestor API."""
    url = f"{INGEST_BASE_URL.rstrip('/')}{path}"
    resp = requests.get(url, headers=_api_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def api_post(path: str, payload: dict[str, Any], timeout: float = 30.0, params: dict[str, str] | None = None) -> dict[str, Any]:
    """POST request to the ingestor API."""
    url = f"{INGEST_BASE_URL.rstrip('/')}{path}"
    resp = requests.post(url, json=payload, headers=_api_headers(), timeout=timeout, params=params)
    resp.raise_for_status()
    return resp.json()


def _build_search_payload(
    *,
    query: str,
    k: int,
    include_documents: bool,
    collection: str,
    filters: dict[str, Any],
    score_threshold: float | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "q": query,
        "k": k,
        "include_documents": include_documents,
    }
    if collection:
        payload["collection"] = collection
    if filters:
        payload["filters"] = filters
    if score_threshold is not None:
        payload["score_threshold"] = score_threshold
    return payload


def api_upload(
    files: list[Any],
    metadata: dict[str, Any] | None = None,
    section: str = "",
    collection: str = "",
    progress_callback: Any = None,
) -> list[dict[str, Any]]:
    """Upload files to /ingest/upload endpoint with optional progress tracking."""
    results = []
    for idx, f in enumerate(files):
        url = f"{INGEST_BASE_URL.rstrip('/')}/ingest/upload"
        file_data = {"file": (f.name, f.getvalue(), f.type or "application/octet-stream")}
        form_data: dict[str, str] = {
            "source_type": "auto",
            "mode": "multimodal",
            "metadata": json.dumps(metadata or {}),
            "section": section,
            "collection": collection,
        }
        resp = requests.post(
            url,
            files=file_data,
            data=form_data,
            headers=_api_headers(),
            timeout=INGEST_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        result["filename"] = result.get("filename") or f.name
        results.append(result)
        if progress_callback:
            progress_callback(idx + 1, len(files), f.name, result)
    return results


def _check_api_health() -> tuple[bool, str]:
    """Return (is_online, status_text)."""
    try:
        resp = requests.get(f"{INGEST_BASE_URL.rstrip('/')}/health", timeout=5)
        if resp.status_code == 200:
            return True, "En ligne"
        return False, f"Code {resp.status_code}"
    except requests.RequestException:
        return False, "Hors ligne"


def _fetch_collections() -> list[dict[str, Any]]:
    """Fetch collections list, return empty list on error."""
    try:
        data = api_get("/collections", timeout=SEARCH_TIMEOUT)
        return data.get("collections", [])
    except requests.RequestException:
        return []


def _fetch_stats(collection_name: str) -> dict[str, Any]:
    """Fetch collection stats, return empty dict on error."""
    try:
        return api_get(f"/stats/{collection_name}", timeout=SEARCH_TIMEOUT)
    except requests.RequestException:
        return {}


def _collection_names(include_empty: bool = False) -> list[str]:
    names: list[str] = []
    for item in _fetch_collections():
        name = str(item.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    for name in UI_KNOWN_COLLECTIONS:
        clean = name.strip()
        if clean and clean not in names:
            names.append(clean)
    names.sort(
        key=lambda value: (
            0 if value == UI_DEFAULT_COLLECTION else 1 if value == "rag_education" else 2 if value == "rag_web3" else 3,
            value,
        )
    )
    if include_empty:
        return [""] + names
    return names


def _collection_index(options: list[str], preferred: str = "") -> int:
    target = preferred or UI_DEFAULT_COLLECTION
    if target in options:
        return options.index(target)
    return 0


def _section_for_collection(collection_name: str) -> str:
    if collection_name in {"rag_francais_premiere", "rag_education"}:
        return "education"
    if collection_name == "rag_web3":
        return "web3"
    return ""


# --- UI Components ---

def _kpi_card(icon: str, value: str | int, label: str) -> None:
    """Render a styled KPI card."""
    st.markdown(
        f'<div class="kpi-card">'
        f'<div class="kpi-icon">{icon}</div>'
        f'<div class="kpi-value">{value}</div>'
        f'<div class="kpi-label">{label}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _status_badge(online: bool, text: str) -> str:
    """Return HTML for a status badge."""
    css_class = "status-online" if online else "status-offline"
    dot = "●"
    return f'<span class="{css_class}">{dot} {text}</span>'


def _score_bar(score: float, max_score: float = 1.0) -> str:
    """Return HTML for a visual score bar."""
    pct = max(0, min(100, (1 - score / max_score) * 100)) if max_score > 0 else 0
    if pct > 70:
        color = "#22C55E"
    elif pct > 40:
        color = "#EAB308"
    else:
        color = "#EF4444"
    return (
        f'<div class="score-bar-container">'
        f'<div class="score-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
        f'</div>'
    )


def _file_icon(filename: str) -> str:
    """Return an icon for the file type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return FILE_TYPE_ICONS.get(ext, "📎")


def _format_file_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _show_ingest_result(result: dict[str, Any]) -> None:
    """Display ingestion result with rich feedback."""
    status = result.get("status", "unknown")
    added = result.get("added", 0)
    skipped = result.get("skipped", 0)
    col_name = result.get("collection", "")
    filename = result.get("filename", "")

    if status == "ok":
        icon = _file_icon(filename) if filename else "✅"
        parts = [f"**{icon} {filename}**"] if filename else ["**Ingestion terminee**"]
        details = []
        if added:
            details.append(f"**{added}** chunk(s) ajoute(s)")
        if skipped:
            details.append(f"**{skipped}** doublon(s) ignore(s)")
        if col_name:
            details.append(f"Collection: `{col_name}`")
        parts.append(" | ".join(details))
        st.markdown(
            f'<div class="ingest-ok">{"<br>".join(parts)}</div>',
            unsafe_allow_html=True,
        )
    else:
        detail = result.get("detail", str(result))
        st.markdown(
            f'<div class="ingest-err">❌ <strong>Erreur</strong>: {detail}</div>',
            unsafe_allow_html=True,
        )


# --- Metadata inputs ---

def _build_metadata_inputs(prefix: str) -> tuple[str, str, dict[str, Any], str, str]:
    """Build source + metadata form inputs with improved layout."""
    options = list(SOURCE_TYPE_MAP.keys())
    source_type = st.selectbox(
        "Type de source",
        options,
        format_func=lambda key: f"{SOURCE_TYPE_MAP[key]['icon']} {SOURCE_TYPE_MAP[key]['label']}",
        key=f"{prefix}type",
    )
    info = SOURCE_TYPE_MAP.get(source_type, {})
    placeholder = info.get("placeholder", "https://exemple.com")
    source = st.text_input(
        "URL / ID GDrive / Chemin local",
        value=st.session_state.get(f"{prefix}source", ""),
        placeholder=placeholder,
        key=f"{prefix}source",
    )
    if source_type in MULTIMODAL_ONLY_TYPES:
        st.info("🎬 Cette source sera traitee en mode multimodal (transcription audio/video).", icon="ℹ️")

    st.markdown("##### Metadonnees du document")
    collection_options = _collection_names()
    collection_name = st.selectbox(
        "Collection cible",
        collection_options,
        index=_collection_index(collection_options),
        key=f"{prefix}collection",
    )
    section_default = _section_for_collection(collection_name)
    section_options = [section_default] + [opt for opt in ["education", "web3", ""] if opt != section_default]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        matiere = st.text_input("Matiere", UI_DEFAULT_MATIERE, key=f"{prefix}matiere")
    with c2:
        voie = st.selectbox("Voie", ["generale", "technologique", "commun"], index=2, key=f"{prefix}voie")
    with c3:
        niveau = st.selectbox("Niveau", ["Premiere", "Terminale"], index=0, key=f"{prefix}niveau")
    with c4:
        section = st.selectbox("Section", section_options, key=f"{prefix}section")

    c5, c6 = st.columns(2)
    with c5:
        doc_type = st.selectbox(
            "Type de document",
            ["programme_officiel", "annale_bac", "cours", "fiche_pedagogique", "td_tp", "corrige"],
            index=2,
            key=f"{prefix}doctype",
        )
    with c6:
        annee = st.number_input(
            "Annee", min_value=2010, max_value=2035, value=2024, key=f"{prefix}annee"
        )

    hints: dict[str, Any] = {
        "matiere": matiere,
        "voie": voie,
        "niveau": niveau,
        "document_type": doc_type,
        "annee_programme": annee,
        "collection": collection_name,
    }
    if section:
        hints["section"] = section
    return source, source_type, hints, collection_name, section


# --- Page: Dashboard ---

def _render_dashboard() -> None:
    """Rich dashboard with KPIs, charts and system status."""
    online, status_text = _check_api_health()
    st.markdown(_status_badge(online, f"API {status_text}"), unsafe_allow_html=True)

    if not online:
        st.error("L'API est inaccessible. Verifiez que les services sont demarres.")
        return

    collections = _fetch_collections()
    total_docs = sum(c.get("count", 0) for c in collections)

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        _kpi_card("📦", len(collections), "Collections")
    with k2:
        _kpi_card("📄", f"{total_docs:,}", "Documents totaux")
    with k3:
        _kpi_card("🧠", os.getenv("EMBED_MODEL", "nomic-embed-text"), "Modele d'embedding")
    with k4:
        _kpi_card("✅" if online else "❌", status_text, "Statut API")

    if not collections:
        st.info("Aucune collection trouvee. Commencez par ingerer des documents.")
        return

    st.markdown("---")

    # Charts row
    col_chart, col_details = st.columns([3, 2])

    with col_chart:
        st.markdown("#### Repartition par collection")
        names = [c.get("name", "?") for c in collections]
        counts = [c.get("count", 0) for c in collections]
        colors = ["#818CF8", "#6366F1", "#4F46E5", "#4338CA", "#3730A3", "#312E81"]

        if go is not None:
            fig = go.Figure(data=[go.Bar(
                x=names,
                y=counts,
                marker_color=colors[:len(names)],
                text=counts,
                textposition="outside",
                textfont={"color": "#E2E8F0", "size": 14},
            )])
            fig.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font={"color": "#E2E8F0"},
                xaxis={"showgrid": False, "color": "#94A3B8"},
                yaxis={"showgrid": True, "gridcolor": "#334155", "color": "#94A3B8"},
                margin={"t": 20, "b": 40, "l": 40, "r": 20},
                height=320,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            for n, c in zip(names, counts, strict=False):
                st.markdown(f"- **{n}**: {c} docs")

    with col_details:
        st.markdown("#### Details des collections")
        for col_info in collections:
            name = col_info.get("name", "?")
            count = col_info.get("count", 0)
            stats = _fetch_stats(name)
            matieres = stats.get("matieres", [])
            niveaux = stats.get("niveaux", [])

            with st.expander(f"📁 **{name}** — {count} doc(s)", expanded=False):
                mc1, mc2 = st.columns(2)
                with mc1:
                    st.metric("Documents", count)
                with mc2:
                    st.metric("Matieres", len(matieres))
                if matieres:
                    tags_html = "".join(
                        f'<span class="result-meta-tag">{m}</span>' for m in matieres
                    )
                    st.markdown(f"**Matieres:** {tags_html}", unsafe_allow_html=True)
                if niveaux:
                    tags_html = "".join(
                        f'<span class="result-meta-tag">{n}</span>' for n in niveaux
                    )
                    st.markdown(f"**Niveaux:** {tags_html}", unsafe_allow_html=True)

    # Donut chart
    if len(collections) > 1:
        st.markdown("---")
        st.markdown("#### Proportion des documents")
        d1, d2 = st.columns([2, 3])
        with d2:
            if go is not None:
                fig_donut = go.Figure(data=[go.Pie(
                    labels=names,
                    values=counts,
                    hole=0.55,
                    marker={"colors": colors[:len(names)]},
                    textinfo="label+percent",
                    textfont={"color": "#E2E8F0", "size": 12},
                )])
                fig_donut.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font={"color": "#E2E8F0"},
                    showlegend=False,
                    margin={"t": 10, "b": 10, "l": 10, "r": 10},
                    height=280,
                )
                st.plotly_chart(fig_donut, use_container_width=True)
        with d1:
            st.markdown("<br>", unsafe_allow_html=True)
            for i, col_info in enumerate(collections):
                name = col_info.get("name", "?")
                count = col_info.get("count", 0)
                pct = (count / total_docs * 100) if total_docs > 0 else 0
                color = colors[i % len(colors)]
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:0.5rem;margin:0.4rem 0">'
                    f'<span style="width:12px;height:12px;border-radius:3px;background:{color};display:inline-block"></span>'
                    f'<span style="color:#E2E8F0;font-weight:600">{name}</span>'
                    f'<span style="color:#94A3B8;margin-left:auto">{count} ({pct:.1f}%)</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# --- Page: Ingestion ---

def _render_upload_tab() -> None:
    """Enhanced file upload tab with progress tracking."""
    st.markdown("#### 📤 Glisser-deposer vos fichiers")
    uploaded = st.file_uploader(
        "Formats acceptes : PDF, Word, Markdown, images, audio, video...",
        type=ACCEPTED_FILE_TYPES,
        accept_multiple_files=True,
        key="upload_files",
        label_visibility="collapsed",
    )

    if uploaded:
        st.markdown(f"**{len(uploaded)} fichier(s) selectionne(s) :**")
        chips_html = ""
        total_size = 0
        for f in uploaded:
            icon = _file_icon(f.name)
            size = len(f.getvalue())
            total_size += size
            chips_html += f'<span class="file-chip">{icon} {f.name} ({_format_file_size(size)})</span>'
        st.markdown(chips_html, unsafe_allow_html=True)
        st.caption(f"Taille totale : {_format_file_size(total_size)}")

    st.markdown("---")
    st.markdown("##### Configuration")
    c1, c2, c3 = st.columns(3)
    with c1:
        collection_options = _collection_names()
        collection_override = st.selectbox(
            "Collection cible",
            collection_options,
            index=_collection_index(collection_options),
            key="upload_collection",
        )
    with c2:
        section_default = _section_for_collection(collection_override)
        section_options = [section_default] + [opt for opt in ["education", "web3", ""] if opt != section_default]
        section = st.selectbox("Section logique", section_options, key="upload_section")
    with c3:
        matiere = st.text_input("Matiere", UI_DEFAULT_MATIERE, key="upload_matiere")

    metadata: dict[str, Any] = {"matiere": matiere, "collection": collection_override}
    if section:
        metadata["section"] = section
    st.caption("Les doublons deja presents dans la collection cible sont detectes automatiquement et ignores pendant le traitement du lot.")

    if uploaded and st.button("🚀 Lancer l'ingestion", key="btn_upload", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Preparation...")
        status_area = st.empty()
        results_area = st.container()

        def on_progress(current: int, total: int, fname: str, result: dict[str, Any]) -> None:
            pct = current / total
            progress_bar.progress(pct, text=f"Traitement {current}/{total} : {fname}")

        try:
            results = api_upload(
                uploaded, metadata=metadata, section=section,
                collection=collection_override, progress_callback=on_progress,
            )
            progress_bar.progress(1.0, text="Termine !")
            added_total = sum(r.get("added", 0) for r in results)
            skipped_total = sum(r.get("skipped", 0) for r in results)
            status_area.success(
                f"✅ Ingestion terminee — **{added_total}** chunk(s) ajoute(s), "
                f"**{skipped_total}** doublon(s) ignore(s)"
            )
            with results_area:
                for r in results:
                    _show_ingest_result(r)
        except requests.HTTPError as exc:
            progress_bar.empty()
            code = exc.response.status_code if exc.response else "?"
            body = exc.response.text[:500] if exc.response else ""
            st.error(f"❌ Erreur API ({code}): {body}")
        except requests.ReadTimeout:
            progress_bar.empty()
            st.warning("⏳ Timeout — le traitement continue cote serveur. Reessayez plus tard.")
        except requests.RequestException as exc:
            progress_bar.empty()
            st.error(f"❌ Erreur reseau: {exc}")


def _render_url_tab() -> None:
    """URL / source ingestion tab with improved UX."""
    st.markdown("#### 🌐 Ingestion depuis une URL ou un chemin")
    with st.form("direct_ingest"):
        source, source_type, hints, collection_name, section = _build_metadata_inputs("direct_")

        st.markdown("---")
        mode_choice = st.selectbox(
            "Mode de traitement",
            ["text", "multimodal"],
            key="direct_mode",
            help="'text' pour les documents textuels, 'multimodal' pour les images/audio/video.",
        )
        if source_type in MULTIMODAL_ONLY_TYPES and mode_choice != "multimodal":
            st.warning("⚠️ Selectionnez le mode 'multimodal' pour traiter une video/audio.")
        st.caption("Pour les URLs, dossiers Google Drive et chemins locaux, les contenus deja presents dans la collection cible sont ignores automatiquement.")

        submitted = st.form_submit_button("🚀 Ingerer", type="primary", use_container_width=True)

    if submitted:
        if not source:
            st.error("Veuillez saisir une source.")
        else:
            payload: dict[str, Any] = {"source": source, "source_type": source_type, "hints": hints}
            with st.spinner("Ingestion en cours..."):
                try:
                    result = api_post(
                        "/ingest", payload, timeout=INGEST_TIMEOUT,
                        params={"mode": mode_choice, "section": section, "collection": collection_name},
                    )
                    _show_ingest_result(result)
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response else "?"
                    body = exc.response.text[:500] if exc.response else ""
                    st.error(f"❌ Erreur API ({code}): {body}")
                except requests.ReadTimeout:
                    st.warning("⏳ Timeout — le traitement continue cote serveur.")
                except requests.RequestException as exc:
                    st.error(f"❌ Erreur reseau: {exc}")


def _render_n8n_tab() -> None:
    """n8n webhook ingestion tab."""
    st.markdown("#### 🔗 Ingestion via webhook n8n")
    webhook_default = N8N_DEFAULT_WEBHOOK or "https://EXEMPLE.webhook.url/ingestion"
    webhook = st.text_input("URL Webhook n8n", webhook_default, help="Configurez votre workflow n8n pour recevoir les ingestions.")

    with st.form("n8n_ingest"):
        source, source_type, hints, _, _ = _build_metadata_inputs("webhook_")
        submitted = st.form_submit_button("📨 Envoyer via n8n", type="primary", use_container_width=True)

    if submitted:
        if not webhook.startswith("http"):
            st.error("URL webhook invalide")
        else:
            payload: dict[str, Any] = {"source": source, "source_type": source_type, "hints": hints}
            with st.spinner("Envoi vers n8n..."):
                try:
                    resp = requests.post(webhook, json=payload, timeout=WEBHOOK_TIMEOUT)
                    resp.raise_for_status()
                    st.success("✅ Webhook accepte par n8n")
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response else "?"
                    st.error(f"❌ n8n a renvoye le code {code}")
                except requests.RequestException as exc:
                    st.error(f"❌ Erreur reseau webhook: {exc}")


def _render_ingestion_page() -> None:
    """Ingestion page with tabs."""
    tab_upload, tab_url, tab_n8n = st.tabs([
        "📤 Upload fichiers",
        "🌐 URL / Source",
        "🔗 Via n8n",
    ])
    with tab_upload:
        _render_upload_tab()
    with tab_url:
        _render_url_tab()
    with tab_n8n:
        _render_n8n_tab()


# --- Page: Search ---

def _render_search() -> None:
    """Enhanced search page with visual results."""
    st.markdown("#### Parametres de recherche")

    c1, c2, c3 = st.columns([4, 1, 1])
    with c1:
        query = st.text_input(
            "🔍 Votre question",
            placeholder="Ex: recursivite en Python, algorithmes de tri, programmes officiels NSI...",
            key="search_q",
            label_visibility="collapsed",
        )
    with c2:
        k = st.slider("Resultats", 1, UI_MAX_K, UI_DEFAULT_K, key="search_k")
    with c3:
        search_collections = _collection_names(include_empty=True)
        collection = st.selectbox(
            "Collection",
            search_collections,
            index=_collection_index(search_collections, UI_DEFAULT_COLLECTION),
            format_func=lambda value: "Toutes" if value == "" else value,
            key="search_collection",
        )

    with st.expander("🎛️ Filtres avances", expanded=False):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            filter_matiere = st.text_input("Matiere", "", key="search_matiere", placeholder="Ex: NSI, Maths...")
        with fc2:
            filter_niveau = st.selectbox("Niveau", ["Tous", "Premiere", "Terminale"], key="search_niveau")
        with fc3:
            include_docs = st.checkbox("Inclure le contenu des documents", value=True, key="search_include_docs")
        with fc4:
            enable_score_threshold = st.checkbox("Seuil distance", value=False, key="search_enable_score_threshold")
            score_threshold = st.number_input(
                "Distance max",
                min_value=0.0,
                max_value=2.0,
                value=0.55,
                step=0.05,
                key="search_score_threshold",
                disabled=not enable_score_threshold,
            )

    search_clicked = st.button("🔍 Rechercher", key="btn_search", type="primary", use_container_width=True)

    if search_clicked:
        if not query:
            st.warning("Veuillez saisir une requete.")
            return

        filters: dict[str, Any] = {}
        if filter_matiere:
            filters["matiere"] = filter_matiere
        if filter_niveau and filter_niveau != "Tous":
            filters["niveau"] = filter_niveau

        payload = _build_search_payload(
            query=query,
            k=k,
            include_documents=include_docs,
            collection=collection,
            filters=filters,
            score_threshold=score_threshold if enable_score_threshold else None,
        )

        with st.spinner("Recherche en cours..."):
            try:
                result = api_post("/search", payload, timeout=SEARCH_TIMEOUT)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response else "?"
                body = exc.response.text[:500] if exc.response else ""
                st.error(f"❌ Erreur API ({code}): {body}")
                return
            except requests.RequestException as exc:
                st.error(f"❌ Erreur reseau: {exc}")
                return

        hits = result.get("hits", [])
        col_name = result.get("collection", "")
        filters_applied = result.get("filters_applied", {})

        # Results header
        st.markdown("---")
        rc1, rc2, rc3 = st.columns([2, 2, 2])
        with rc1:
            st.markdown(f"**{len(hits)}** resultat(s)")
        with rc2:
            if col_name:
                st.markdown(f"Collection: `{col_name}`")
        with rc3:
            if filters_applied:
                st.markdown(f"Filtres: {filters_applied}")

        if not hits:
            st.info("🔍 Aucun resultat trouve. Essayez avec des termes differents ou moins de filtres.")
            return

        # Find max distance for normalization
        distances = [h.get("score", 0) for h in hits if h.get("score") is not None]
        max_dist = max(distances) if distances else 1.0

        for i, hit in enumerate(hits):
            score = hit.get("score")
            meta = hit.get("metadata", {})
            doc_text = hit.get("document", "")

            # Build meta tags
            meta_tags = ""
            for tag_key in ("matiere", "niveau", "voie", "document_type", "source"):
                val = meta.get(tag_key, "")
                if val:
                    meta_tags += f'<span class="result-meta-tag">{tag_key}: {val}</span>'

            score_html = ""
            if score is not None:
                relevance = max(0, (1 - score / max_dist) * 100) if max_dist > 0 else 0
                score_html = (
                    f'<span class="result-score">{relevance:.0f}%</span> '
                    f'<span style="color:#94A3B8;font-size:0.8rem">pertinence</span>'
                    f'{_score_bar(score, max_dist)}'
                )

            st.markdown(
                f'<div class="result-card">'
                f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                f'<span class="result-rank">Resultat #{i + 1}</span>'
                f'<div style="text-align:right;min-width:120px">{score_html}</div>'
                f'</div>'
                f'<div style="margin-top:0.5rem">{meta_tags}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if doc_text:
                with st.expander(f"📄 Voir le contenu (resultat #{i + 1})", expanded=(i == 0)):
                    st.markdown(f"```\n{doc_text[:2000]}\n```")
                    if len(doc_text) > 2000:
                        st.caption(f"... {len(doc_text) - 2000} caractere(s) supplementaire(s) tronque(s)")

            if meta:
                with st.expander(f"🏷️ Metadonnees (resultat #{i + 1})", expanded=False):
                    st.dataframe(
                        pd.DataFrame(
                            list(meta.items()),
                            columns=pd.Index(["Champ", "Valeur"]),
                        ),
                        use_container_width=True,
                        hide_index=True,
                    )


# --- Page: Exploration ---

def _render_exploration() -> None:
    """Browse and explore ingested documents by collection."""
    online, _ = _check_api_health()
    if not online:
        st.error("L'API est inaccessible.")
        return

    collections = _fetch_collections()
    if not collections:
        st.info("Aucune collection trouvee.")
        return

    # Collection selector
    col_names = [c.get("name", "?") for c in collections]
    col_counts = {c.get("name", "?"): c.get("count", 0) for c in collections}

    selected = st.selectbox(
        "Selectionner une collection",
        col_names,
        index=_collection_index(col_names, UI_DEFAULT_COLLECTION),
        format_func=lambda n: f"📁 {n} ({col_counts.get(n, 0)} docs)",
        key="explore_collection",
    )

    if not selected:
        return

    stats = _fetch_stats(selected)
    doc_count = stats.get("doc_count", col_counts.get(selected, 0))
    matieres = stats.get("matieres", [])
    niveaux = stats.get("niveaux", [])
    groupes = stats.get("groupes", [])
    types_ressource = stats.get("types_ressource", [])

    # Stats overview
    st.markdown("---")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        _kpi_card("📄", doc_count, "Documents")
    with s2:
        _kpi_card("📚", len(matieres), "Matieres")
    with s3:
        _kpi_card("🎓", len(niveaux), "Niveaux")
    with s4:
        _kpi_card("📋", len(types_ressource) if types_ressource else "—", "Types")

    # Tags display
    if matieres or niveaux or groupes:
        st.markdown("#### 🏷️ Taxonomie")
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            if matieres:
                tags = "".join(f'<span class="result-meta-tag">{m}</span>' for m in sorted(matieres))
                st.markdown(f"**Matieres :** {tags}", unsafe_allow_html=True)
        with tc2:
            if niveaux:
                tags = "".join(f'<span class="result-meta-tag">{n}</span>' for n in sorted(niveaux))
                st.markdown(f"**Niveaux :** {tags}", unsafe_allow_html=True)
        with tc3:
            if types_ressource:
                tags = "".join(f'<span class="result-meta-tag">{t}</span>' for t in sorted(types_ressource))
                st.markdown(f"**Types :** {tags}", unsafe_allow_html=True)

    # Sample documents
    st.markdown("---")
    st.markdown("#### 📖 Apercu des documents")
    st.caption("Affichage d'un echantillon representatif de la collection.")

    try:
        peek_data = api_get(f"/stats/{selected}", timeout=SEARCH_TIMEOUT)
        sample_docs = peek_data.get("sample_documents", [])
        sample_ids = peek_data.get("sample_ids", [])
        sample_metas = peek_data.get("sample_metadatas", [])

        if sample_docs:
            for idx, doc_text in enumerate(sample_docs[:10]):
                doc_id = sample_ids[idx] if idx < len(sample_ids) else f"doc-{idx}"
                meta = sample_metas[idx] if idx < len(sample_metas) else {}
                source_name = meta.get("source", meta.get("filename", doc_id))
                matiere_tag = meta.get("matiere", "")

                header_tags = ""
                if matiere_tag:
                    header_tags += f'<span class="result-meta-tag">{matiere_tag}</span>'

                st.markdown(
                    f'<div class="doc-card">'
                    f'<div class="doc-card-title">📄 {source_name}</div>'
                    f'<div class="doc-card-meta">ID: {doc_id} {header_tags}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"Voir le contenu — {source_name}", expanded=False):
                    preview = doc_text[:1500] if isinstance(doc_text, str) else str(doc_text)[:1500]
                    st.code(preview, language=None)
        else:
            st.info("Pas d'apercu disponible pour cette collection.")
    except requests.RequestException:
        st.warning("Impossible de charger l'apercu des documents.")

    # Search within collection
    st.markdown("---")
    st.markdown("#### 🔍 Recherche dans cette collection")
    explore_query = st.text_input(
        "Rechercher dans la collection",
        placeholder=f"Rechercher dans {selected}...",
        key="explore_search_q",
    )
    if explore_query and st.button("Rechercher", key="btn_explore_search"):
        payload: dict[str, Any] = {"q": explore_query, "k": 5, "include_documents": True, "collection": selected}
        with st.spinner("Recherche..."):
            try:
                result = api_post("/search", payload, timeout=SEARCH_TIMEOUT)
                hits = result.get("hits", [])
                if hits:
                    for i, hit in enumerate(hits):
                        doc_text = hit.get("document", "")
                        meta = hit.get("metadata", {})
                        score = hit.get("score")
                        label = f"#{i+1}"
                        if score is not None:
                            relevance = max(0, (1 - score) * 100)
                            label += f" — {relevance:.0f}% pertinence"
                        with st.expander(label, expanded=(i == 0)):
                            if doc_text:
                                st.code(doc_text[:1000], language=None)
                            if meta:
                                tags = " ".join(
                                    f'`{k}: {v}`' for k, v in meta.items()
                                    if v and k not in ("content_hash", "chunk_index")
                                )
                                st.caption(tags)
                else:
                    st.info("Aucun resultat.")
            except requests.RequestException as exc:
                st.error(f"Erreur: {exc}")


# --- Page: Administration ---

def _render_admin() -> None:
    """Administration page with system overview."""
    st.warning("🔒 Protegez cette section derriere un proxy authentifie (Nginx Basic Auth).", icon="⚠️")

    # System status
    st.markdown("#### Etat du systeme")
    online, status_text = _check_api_health()
    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        _kpi_card("🖥️", status_text, "API Ingestor")
    with sc2:
        _kpi_card("💾", os.getenv("CHROMA_HOST", "chroma"), "ChromaDB")
    with sc3:
        _kpi_card("🤖", os.getenv("OLLAMA_URL", "http://ollama:11434"), "Ollama")

    # Configuration
    st.markdown("---")
    st.markdown("#### Configuration active")
    config_items = {
        "API Base URL": INGEST_BASE_URL,
        "Token configure": "Oui" if INGEST_API_TOKEN else "Non",
        "Modele d'embedding": os.getenv("EMBED_MODEL", "nomic-embed-text"),
        "Timeout ingestion": f"{INGEST_TIMEOUT}s",
        "Timeout recherche": f"{SEARCH_TIMEOUT}s",
        "Max resultats (k)": str(UI_MAX_K),
        "Multimodal": os.getenv("MULTIMODAL_ENABLED", "true"),
        "Metriques Prometheus": os.getenv("METRICS_ENABLED", "true"),
    }
    st.dataframe(
        pd.DataFrame(
            list(config_items.items()),
            columns=pd.Index(["Parametre", "Valeur"]),
        ),
        use_container_width=True,
        hide_index=True,
    )

    # Collections management
    st.markdown("---")
    st.markdown("#### Collections")
    if online:
        _render_dashboard()
    else:
        st.error("API inaccessible — impossible d'afficher les collections.")


# --- Main App ---

def render_app() -> None:
    """Main application entry point."""
    st.set_page_config(
        layout="wide",
        page_title="RAG Pedagogique — Admin",
        page_icon="🎓",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

    # Sidebar
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-brand">'
            '<h2>🎓 RAG Pedagogique</h2>'
            '<p>Plateforme d\'ingestion & recherche</p>'
            '</div>',
            unsafe_allow_html=True,
        )

        page = st.radio(
            "Navigation",
            [item["key"] for item in NAV_ITEMS],
            format_func=lambda k: next(
                (f"{item['icon']}  {item['label']}" for item in NAV_ITEMS if item["key"] == k),
                k,
            ),
            key="nav",
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Sidebar health indicator
        online, status_text = _check_api_health()
        st.markdown(_status_badge(online, f"API: {status_text}"), unsafe_allow_html=True)

        st.markdown(
            '<div style="position:fixed;bottom:1rem;color:#64748B;font-size:0.7rem">'
            'RAG Pedagogique v1.0'
            '</div>',
            unsafe_allow_html=True,
        )

    # Page routing
    if page == "dashboard":
        st.title("📊 Tableau de bord")
        _render_dashboard()

    elif page == "ingestion":
        st.title("📥 Ingestion de ressources")
        _render_ingestion_page()

    elif page == "search":
        st.title("🔍 Recherche semantique")
        _render_search()

    elif page == "explore":
        st.title("📚 Exploration des collections")
        _render_exploration()

    elif page == "admin":
        st.title("⚙️ Administration")
        _render_admin()


if not STREAMLIT_IMPORT_ONLY:
    render_app()
