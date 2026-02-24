"""
Dashboard RAG v2 — Streamlit
Fonctionnalités :
- Statistiques par tenant (docs, chunks, modèle d'embedding)
- Ingestion multimodale : Google Drive, liste d'URLs, upload multi-fichiers
- Section Éducation avec taxonomie complète (Enseignements communs, spécialité, optionnels, Grand Oral)
- Recherche interactive avec affichage des scores dense/sparse/rerank
- Évaluation RAG (precision@5, recall@5, MRR) avec historique
- Vérification de doublons avant ingestion
- Monitoring : latences, cache hit rate, erreurs
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pandas as pd
import streamlit as st

# Configuration
st.set_page_config(
    page_title="RAG Dashboard — Nexus Réussite",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

RAG_API_URL = os.getenv("RAG_API_URL", "http://ingestor:8001")
RAG_API_TOKEN = os.getenv("RAG_API_TOKEN", "")

# ═══════════════════════════════════════════════════════════════
# TAXONOMIE ÉDUCATION COMPLÈTE — Programmes Lycée Général
# ═══════════════════════════════════════════════════════════════

EDUCATION_CATEGORIES: dict[str, list[str]] = {
    "Enseignements communs": [
        "Français",
        "Philosophie",
        "Histoire-géographie",
        "LVA et LVB (enveloppe globalisée)",
        "Enseignement scientifique",
        "Enseignement moral et civique",
        "Accompagnement au choix de l'orientation",
    ],
    "Enseignements de spécialité": [
        "Arts",
        "Biologie-écologie",
        "Histoire-géographie, géopolitique et sciences politiques",
        "Humanités, littérature et philosophie",
        "Langues, littératures et cultures étrangères et régionales",
        "Littératures et langues et cultures de l'Antiquité",
        "Mathématiques",
        "Numérique et sciences informatiques",
        "Physique-chimie",
        "Sciences de la vie et de la Terre",
        "Sciences de l'ingénieur",
        "Sciences économiques et sociales",
    ],
    "Enseignements optionnels — Terminale uniquement": [
        "Mathématiques complémentaires",
        "Mathématiques expertes",
        "Droits et grands enjeux du monde contemporain",
    ],
    "Enseignements optionnels — 1ère et/ou Terminale": [
        "Langue vivante C",
        "LCA : latin",
        "LCA : grec",
        "Arts",
        "Langue des signes française",
        "Agronomie, économie, territoires",
        "Pratiques sociales et culturelles",
    ],
    "Épreuves": [
        "Grand Oral",
    ],
}

# Flatten pour sélection rapide
ALL_CATEGORIES_FLAT: list[str] = []
for group_name, items in EDUCATION_CATEGORIES.items():
    for item in items:
        label = f"{group_name} > {item}"
        if label not in ALL_CATEGORIES_FLAT:
            ALL_CATEGORIES_FLAT.append(label)


# ═══════════════════════════════════════════════════════════════
# HELPERS API
# ═══════════════════════════════════════════════════════════════

def api_headers() -> dict[str, str]:
    """Retourne les headers d'authentification pour l'API RAG."""
    return {
        "Authorization": f"Bearer {RAG_API_TOKEN}",
        "Content-Type": "application/json",
    }


def api_get(endpoint: str, timeout: float = 30.0) -> dict[str, Any] | None:
    """Effectue un GET vers l'API RAG avec gestion d'erreurs."""
    try:
        resp = httpx.get(
            f"{RAG_API_URL}{endpoint}",
            headers=api_headers(),
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        st.error(f"API error {resp.status_code}: {resp.text}")
    except Exception as exc:
        st.error(f"Connexion API échouée: {exc}")
    return None


def api_post(endpoint: str, data: dict[str, Any], timeout: float = 30.0) -> dict[str, Any] | None:
    """Effectue un POST vers l'API RAG avec gestion d'erreurs."""
    try:
        resp = httpx.post(
            f"{RAG_API_URL}{endpoint}",
            json=data,
            headers=api_headers(),
            timeout=timeout,
        )
        if resp.status_code in (200, 202):
            return resp.json()
        st.error(f"API error {resp.status_code}: {resp.text}")
    except Exception as exc:
        st.error(f"Connexion API échouée: {exc}")
    return None


def api_upload_files(
    endpoint: str,
    files: list[tuple[str, bytes, str]],
    params: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any] | None:
    """Upload multiple files vers l'API RAG."""
    try:
        multipart_files = [
            ("files", (name, content, mime))
            for name, content, mime in files
        ]
        headers = {"Authorization": f"Bearer {RAG_API_TOKEN}"}
        resp = httpx.post(
            f"{RAG_API_URL}{endpoint}",
            files=multipart_files,
            params=params or {},
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code in (200, 202):
            return resp.json()
        st.error(f"API error {resp.status_code}: {resp.text}")
    except Exception as exc:
        st.error(f"Upload échoué: {exc}")
    return None


# ── Sidebar navigation ────────────────────────────────────────
page = st.sidebar.selectbox(
    "Navigation",
    [
        "📊 Statistiques",
        "🎓 Éducation",
        "📥 Ingestion",
        "🔍 Recherche",
        "📈 Évaluation",
        "🔧 Admin",
    ],
)

TENANT = st.sidebar.selectbox("Tenant", ["nsi", "nexus", "mfai", "web3"])

st.sidebar.markdown("---")
st.sidebar.caption(f"API: `{RAG_API_URL}`")
st.sidebar.caption(f"Tenant: `{TENANT}`")

# ═══════════════════════════════════════════════════════════════
# PAGE STATISTIQUES
# ═══════════════════════════════════════════════════════════════
if page == "📊 Statistiques":
    st.title("📊 Statistiques RAG")

    data = api_get(f"/stats/{TENANT}")
    if data:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Documents", data.get("doc_count", 0))
        col2.metric("Chunks", data.get("chunk_count", 0))
        col3.metric("Modèle", data.get("embed_model", "—"))
        col4.metric("Dernière MAJ", str(data.get("last_updated", "—"))[:19])

    # Historique des évaluations
    st.subheader("📈 Qualité RAG dans le temps")
    eval_data = api_get(f"/eval/history/{TENANT}")
    if eval_data:
        runs = eval_data.get("runs", [])
        if runs:
            df = pd.DataFrame(runs)
            if "run_at" in df.columns:
                df["run_at"] = pd.to_datetime(df["run_at"])
                metrics_cols = [c for c in ["precision_at_5", "recall_at_5", "mrr"] if c in df.columns]
                if metrics_cols:
                    st.line_chart(df.set_index("run_at")[metrics_cols])
        else:
            st.info("Aucune évaluation enregistrée. Lancez-en une depuis l'onglet Évaluation.")

    # Documents récents
    st.subheader("📄 Documents récents")
    docs_data = api_get(f"/admin/documents?domain={TENANT}")
    if docs_data:
        docs = docs_data.get("documents", [])
        if docs:
            df_docs = pd.DataFrame(docs)
            display_cols = [c for c in ["title", "source_type", "chunk_count", "ingested_at"] if c in df_docs.columns]
            if display_cols:
                st.dataframe(df_docs[display_cols], use_container_width=True)
        else:
            st.info("Aucun document pour ce tenant.")

# ═══════════════════════════════════════════════════════════════
# PAGE ÉDUCATION — Ingestion avec taxonomie complète
# ═══════════════════════════════════════════════════════════════
elif page == "🎓 Éducation":
    st.title("🎓 Éducation — Ingérer des ressources")
    st.markdown(
        "Ingérez des ressources éducatives classées par catégorie du programme "
        "du lycée général (Enseignements communs, de spécialité, optionnels, Grand Oral)."
    )

    # ── Sélection de la catégorie ──
    st.subheader("📂 Catégorie")

    # Afficher les groupes avec indentation
    group_names = list(EDUCATION_CATEGORIES.keys())
    selected_group = st.selectbox("Groupe d'enseignement", group_names)

    categories_in_group = EDUCATION_CATEGORIES.get(selected_group, [])
    selected_category = st.selectbox("Matière / Catégorie", categories_in_group)

    niveau = st.selectbox("Niveau", ["Première", "Terminale", "Première et Terminale"])

    st.markdown("---")

    # ── Métadonnées communes ──
    edu_metadata = {
        "section": "education",
        "groupe": selected_group,
        "matiere": selected_category,
        "niveau": niveau,
        "tenant": TENANT,
    }

    # ── Tabs d'ingestion ──
    tab_upload, tab_urls, tab_drive = st.tabs([
        "📁 Déposer des fichiers",
        "🔗 Liste d'URLs",
        "☁️ Google Drive",
    ])

    # ── TAB 1: Upload de fichiers ──
    with tab_upload:
        st.markdown("**Formats supportés** : PDF, DOCX, Markdown, TXT, images (OCR), audio, vidéo")

        uploaded_files = st.file_uploader(
            "Glissez-déposez vos fichiers ici",
            type=["pdf", "docx", "doc", "md", "txt", "csv", "html",
                  "jpg", "jpeg", "png", "gif", "bmp", "webp",
                  "mp3", "wav", "m4a", "mp4", "avi", "mkv"],
            accept_multiple_files=True,
            key="edu_file_upload",
        )

        if uploaded_files:
            st.info(f"{len(uploaded_files)} fichier(s) sélectionné(s)")

            # Aperçu des fichiers
            file_info = []
            for f in uploaded_files:
                file_info.append({
                    "Nom": f.name,
                    "Taille": f"{f.size / 1024:.1f} Ko",
                    "Type": f.type or "inconnu",
                })
            st.dataframe(pd.DataFrame(file_info), use_container_width=True, hide_index=True)

            if st.button("🚀 Ingérer les fichiers", key="btn_upload_edu"):
                with st.spinner(f"Ingestion de {len(uploaded_files)} fichier(s) en cours..."):
                    files_payload = []
                    for f in uploaded_files:
                        content = f.read()
                        mime = f.type or "application/octet-stream"
                        files_payload.append((f.name, content, mime))

                    result = api_upload_files(
                        "/ingest/upload-files",
                        files_payload,
                        params={"metadata": json.dumps(edu_metadata)},
                    )

                if result:
                    added = result.get("total_added", 0)
                    skipped = result.get("total_skipped", 0)
                    if added > 0:
                        st.success(f"✅ {added} chunk(s) ajouté(s), {skipped} doublon(s) ignoré(s)")
                    elif skipped > 0:
                        st.warning(f"⚠️ Tous les fichiers étaient déjà ingérés ({skipped} doublons)")
                    else:
                        st.info("Aucun contenu éligible à l'ingestion.")

                    # Détails par fichier
                    for item in result.get("results", []):
                        status_icon = {"ok": "✅", "duplicate": "⚠️", "empty": "⬜", "error": "❌"}.get(
                            item.get("status", ""), "❓"
                        )
                        st.caption(
                            f"{status_icon} **{item.get('filename', '?')}** — "
                            f"{item.get('status', '?')} "
                            f"(ajoutés: {item.get('added', 0)}, ignorés: {item.get('skipped', 0)})"
                        )

    # ── TAB 2: Liste d'URLs ──
    with tab_urls:
        st.markdown("Entrez une URL par ligne. Les doublons seront automatiquement détectés et ignorés.")

        urls_text = st.text_area(
            "URLs (une par ligne)",
            height=200,
            placeholder="https://eduscol.education.fr/document/...\nhttps://www.education.gouv.fr/...",
            key="edu_urls_input",
        )

        if urls_text.strip():
            urls_list = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
            st.info(f"{len(urls_list)} URL(s) détectée(s)")

            # Bouton vérification doublons
            col_check, col_ingest = st.columns(2)

            with col_check:
                if st.button("🔍 Vérifier les doublons", key="btn_check_urls_edu"):
                    with st.spinner("Vérification des doublons..."):
                        check_result = api_post(
                            "/ingest/check-duplicates",
                            {"sources": urls_list},
                        )
                    if check_result:
                        for item in check_result.get("results", []):
                            icon = "⚠️ Déjà ingéré" if item.get("already_ingested") else "✅ Nouveau"
                            st.caption(f"{icon} — `{item.get('source', '?')}`")

            with col_ingest:
                if st.button("🚀 Ingérer les URLs", key="btn_ingest_urls_edu"):
                    with st.spinner(f"Ingestion de {len(urls_list)} URL(s)..."):
                        result = api_post(
                            "/ingest/urls",
                            {"urls": urls_list, "metadata": edu_metadata},
                            timeout=300.0,
                        )
                    if result:
                        added = result.get("total_added", 0)
                        skipped = result.get("total_skipped", 0)
                        st.success(f"✅ {added} chunk(s) ajouté(s), {skipped} doublon(s) ignoré(s)")
                        for item in result.get("results", []):
                            status_icon = {"ok": "✅", "empty": "⬜", "error": "❌"}.get(
                                item.get("status", ""), "❓"
                            )
                            st.caption(
                                f"{status_icon} `{item.get('url', '?')}` — "
                                f"{item.get('status', '?')} "
                                f"(ajoutés: {item.get('added', 0)})"
                            )

    # ── TAB 3: Google Drive ──
    with tab_drive:
        st.markdown(
            "Connectez un dossier Google Drive pour ingérer automatiquement son contenu. "
            "Les fichiers déjà ingérés ou non modifiés seront ignorés."
        )

        drive_folder_id = st.text_input(
            "ID du dossier Google Drive",
            placeholder="1ABC2DEF3GHI4JKL5MNO...",
            key="edu_drive_folder",
            help="Copiez l'ID depuis l'URL du dossier Drive : drive.google.com/drive/folders/<ID>",
        )

        if drive_folder_id.strip() and st.button("☁️ Lancer l'ingestion Drive", key="btn_drive_edu"):
            with st.spinner("Ingestion Google Drive en cours (arrière-plan)..."):
                result = api_post(
                    "/ingest/drive",
                    {
                        "folder_id": drive_folder_id.strip(),
                        "metadata": edu_metadata,
                    },
                    timeout=30.0,
                )
            if result:
                st.success(
                    f"✅ {result.get('message', 'Ingestion lancée.')} "
                    "Les fichiers déjà ingérés seront automatiquement ignorés."
                )

    # ── Référentiel des catégories ──
    st.markdown("---")
    with st.expander("📋 Référentiel complet des catégories", expanded=False):
        for group_name, items in EDUCATION_CATEGORIES.items():
            st.markdown(f"**{group_name}**")
            for item in items:
                st.caption(f"  • {item}")


# ═══════════════════════════════════════════════════════════════
# PAGE RECHERCHE
# ═══════════════════════════════════════════════════════════════
elif page == "🔍 Recherche":
    st.title("🔍 Recherche RAG")

    query = st.text_input(
        "Question",
        placeholder="Qu'est-ce que la complexité algorithmique ?",
    )

    col1, col2, col3 = st.columns(3)
    k = col1.slider("Résultats (k)", 1, 20, 5)
    alpha = col2.slider("Dense vs Sparse (alpha)", 0.0, 1.0, 0.7, 0.05)
    use_rerank = col3.checkbox("Reranking", value=True)

    if query and st.button("🔎 Rechercher"):
        with st.spinner("Recherche hybride en cours..."):
            result = api_post(
                "/search",
                {
                    "query": query,
                    "tenant": TENANT,
                    "k": k,
                    "alpha": alpha,
                    "rerank": use_rerank,
                },
                timeout=60.0,
            )

        if result:
            hits = result.get("hits", result.get("results", []))
            latency = result.get("latency_ms", "?")
            st.info(f"{len(hits)} résultats — latence : {latency}ms")

            for i, r in enumerate(hits):
                rerank_score = r.get("rerank_score", 0)
                dense_score = r.get("score", 0)
                title = r.get("title", r.get("metadata", {}).get("source", "Sans titre"))

                with st.expander(
                    f"#{i+1} — {title} "
                    f"(score: {rerank_score:.3f})"
                ):
                    st.markdown(r.get("document", r.get("text", "")))
                    meta = r.get("metadata", {})
                    col_a, col_b, col_c = st.columns(3)
                    col_a.caption(f"Score dense: {dense_score:.4f}")
                    col_b.caption(f"Score rerank: {rerank_score:.4f}")
                    col_c.caption(f"Source: {meta.get('source', r.get('source_path', '?'))}")
                    if meta.get("matiere"):
                        st.caption(f"📚 Matière: {meta.get('matiere')} | Niveau: {meta.get('niveau', '?')}")


# ═══════════════════════════════════════════════════════════════
# PAGE INGESTION GÉNÉRALE
# ═══════════════════════════════════════════════════════════════
elif page == "📥 Ingestion":
    st.title("📥 Ingestion de documents")
    st.markdown("Ingestion générale (tous tenants). Pour l'éducation, utilisez la page 🎓 Éducation.")

    tab_upload, tab_urls, tab_drive, tab_status = st.tabs([
        "📁 Déposer des fichiers",
        "🔗 Liste d'URLs",
        "☁️ Google Drive",
        "📋 Statut des tâches",
    ])

    # ── TAB 1: Upload fichiers ──
    with tab_upload:
        st.markdown("**Formats supportés** : PDF, DOCX, Markdown, TXT, images (OCR), audio, vidéo")

        uploaded_files = st.file_uploader(
            "Glissez-déposez vos fichiers",
            type=["pdf", "docx", "doc", "md", "txt", "csv", "html",
                  "jpg", "jpeg", "png", "gif", "bmp", "webp",
                  "mp3", "wav", "m4a", "mp4", "avi", "mkv"],
            accept_multiple_files=True,
            key="general_file_upload",
        )

        custom_metadata = st.text_area(
            "Métadonnées JSON (optionnel)",
            value="{}",
            height=80,
            key="general_upload_meta",
        )

        if uploaded_files and st.button("🚀 Ingérer les fichiers", key="btn_upload_general"):
            try:
                meta = json.loads(custom_metadata)
            except Exception:
                meta = {}

            with st.spinner(f"Ingestion de {len(uploaded_files)} fichier(s)..."):
                files_payload = []
                for f in uploaded_files:
                    content = f.read()
                    mime = f.type or "application/octet-stream"
                    files_payload.append((f.name, content, mime))

                result = api_upload_files(
                    "/ingest/upload-files",
                    files_payload,
                    params={"metadata": json.dumps(meta)},
                )

            if result:
                added = result.get("total_added", 0)
                skipped = result.get("total_skipped", 0)
                st.success(f"✅ {added} chunk(s) ajouté(s), {skipped} doublon(s) ignoré(s)")
                for item in result.get("results", []):
                    status_icon = {"ok": "✅", "duplicate": "⚠️", "empty": "⬜", "error": "❌"}.get(
                        item.get("status", ""), "❓"
                    )
                    st.caption(f"{status_icon} **{item.get('filename', '?')}** — {item.get('status', '?')}")

    # ── TAB 2: Liste d'URLs ──
    with tab_urls:
        urls_text = st.text_area(
            "URLs (une par ligne)",
            height=200,
            placeholder="https://example.com/doc1\nhttps://example.com/doc2",
            key="general_urls_input",
        )

        custom_meta_urls = st.text_area(
            "Métadonnées JSON (optionnel)",
            value="{}",
            height=80,
            key="general_urls_meta",
        )

        if urls_text.strip():
            urls_list = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
            st.info(f"{len(urls_list)} URL(s)")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔍 Vérifier doublons", key="btn_check_urls_general"):
                    with st.spinner("Vérification..."):
                        check = api_post("/ingest/check-duplicates", {"sources": urls_list})
                    if check:
                        for item in check.get("results", []):
                            icon = "⚠️" if item.get("already_ingested") else "✅"
                            st.caption(f"{icon} `{item.get('source', '?')}`")

            with col_b:
                if st.button("🚀 Ingérer les URLs", key="btn_ingest_urls_general"):
                    try:
                        meta = json.loads(custom_meta_urls)
                    except Exception:
                        meta = {}

                    with st.spinner(f"Ingestion de {len(urls_list)} URL(s)..."):
                        result = api_post(
                            "/ingest/urls",
                            {"urls": urls_list, "metadata": meta},
                            timeout=300.0,
                        )
                    if result:
                        st.success(
                            f"✅ {result.get('total_added', 0)} chunk(s) ajouté(s), "
                            f"{result.get('total_skipped', 0)} doublon(s)"
                        )

    # ── TAB 3: Google Drive ──
    with tab_drive:
        st.markdown(
            "Connectez un dossier Google Drive. Les fichiers déjà ingérés "
            "ou non modifiés seront automatiquement ignorés."
        )

        drive_folder_id = st.text_input(
            "ID du dossier Google Drive",
            placeholder="1ABC2DEF3GHI...",
            key="general_drive_folder",
        )

        drive_metadata = st.text_area(
            "Métadonnées JSON (optionnel)",
            value="{}",
            height=80,
            key="general_drive_meta",
        )

        if drive_folder_id.strip() and st.button("☁️ Lancer l'ingestion Drive", key="btn_drive_general"):
            try:
                meta = json.loads(drive_metadata)
            except Exception:
                meta = {}

            with st.spinner("Lancement de l'ingestion Drive..."):
                result = api_post(
                    "/ingest/drive",
                    {"folder_id": drive_folder_id.strip(), "metadata": meta},
                    timeout=30.0,
                )
            if result:
                st.success(f"✅ {result.get('message', 'Ingestion lancée.')}")

    # ── TAB 4: Statut des tâches ──
    with tab_status:
        task_id_input = st.text_input("ID de tâche à vérifier", key="task_status_input")
        if task_id_input and st.button("Vérifier", key="btn_check_task"):
            status_data = api_get(f"/ingest/{task_id_input}/status")
            if status_data:
                st.json(status_data)


# ═══════════════════════════════════════════════════════════════
# PAGE ÉVALUATION
# ═══════════════════════════════════════════════════════════════
elif page == "📈 Évaluation":
    st.title("📈 Évaluation de la qualité RAG")
    st.markdown(
        "Lance une évaluation sur le gold set du tenant sélectionné. "
        "Le gold set contient des questions de référence et les résultats attendus."
    )

    if st.button("🚀 Lancer l'évaluation"):
        with st.spinner("Évaluation en cours (peut prendre 1-2 minutes)..."):
            result = api_post(f"/eval/{TENANT}", {}, timeout=120.0)

        if result:
            col1, col2, col3 = st.columns(3)
            col1.metric("Precision@5", f"{result.get('precision_at_5', 0):.3f}")
            col2.metric("Recall@5", f"{result.get('recall_at_5', 0):.3f}")
            col3.metric("MRR", f"{result.get('mrr', 0):.3f}")

            if result.get("avg_latency_ms"):
                st.metric("Latence moyenne", f"{result['avg_latency_ms']:.0f}ms")

            st.subheader("Détails")
            st.json(result)

    # Historique
    st.subheader("📜 Historique des évaluations")
    history = api_get(f"/eval/history/{TENANT}")
    if history:
        runs = history.get("runs", [])
        if runs:
            df = pd.DataFrame(runs)
            display_cols = [
                c for c in ["run_at", "precision_at_5", "recall_at_5", "mrr", "avg_latency_ms", "embed_model"]
                if c in df.columns
            ]
            if display_cols:
                st.dataframe(df[display_cols], use_container_width=True)
        else:
            st.info("Aucune évaluation enregistrée.")


# ═══════════════════════════════════════════════════════════════
# PAGE ADMIN
# ═══════════════════════════════════════════════════════════════
elif page == "🔧 Admin":
    st.title("🔧 Administration RAG")

    # Health check
    st.subheader("🏥 Santé du service")
    health = api_get("/health")
    if health:
        st.success(
            f"✅ Service opérationnel — "
            f"version {health.get('version', '?')}, "
            f"store: {health.get('vector_store', '?')}"
        )

    # Tenants
    st.subheader("🏢 Tenants")
    tenants_data = api_get("/admin/documents")
    if tenants_data:
        docs = tenants_data.get("documents", [])
        if docs:
            st.write(f"{len(docs)} documents au total")

    # Cache stats
    st.subheader("💾 Cache embeddings")
    stats = api_get(f"/stats/{TENANT}")
    if stats and stats.get("cache_stats"):
        cs = stats["cache_stats"]
        col1, col2, col3 = st.columns(3)
        col1.metric("Hits", cs.get("hits", 0))
        col2.metric("Misses", cs.get("misses", 0))
        col3.metric("Hit Rate", f"{cs.get('hit_rate_pct', 0)}%")
