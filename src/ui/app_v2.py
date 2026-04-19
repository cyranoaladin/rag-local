"""
Dashboard RAG v3 — Streamlit
Architecture multi-collection optimisée pour agents IA :
  - rag_education        : accompagnement scolaire, cours, soutien, ressources pédagogiques
  - rag_francais_premiere: corpus dédié Français Première
  - rag_web3             : blockchain, DeFi, NFT, Solana, smart-contracts
  - rag_divers           : ressources variées consultées automatiquement sur toute requête
Ingestion multi-méthodes : Upload fichiers, URLs, Google Drive
Taxonomie complète : Enseignements communs, EDS, options, Grand Oral
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="RAG Dashboard — Nexus Réussite",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_BASE = os.getenv("INGEST_API_BASE", os.getenv("RAG_API_URL", "http://ingestor:8001"))
API_TOKEN = os.getenv("INGEST_API_TOKEN", os.getenv("RAG_API_TOKEN", ""))

# ═══════════════════════════════════════════════════════════════
# TAXONOMIE ÉDUCATION — Programmes Lycée Général complet
# ═══════════════════════════════════════════════════════════════

EDUCATION_TAXONOMY: dict[str, list[str]] = {
    "Enseignements communs": [
        "Français",
        "Philosophie",
        "Histoire-géographie",
        "LVA et LVB (enveloppe globalisée)",
        "Enseignement scientifique",
        "Éducation physique et sportive",
        "Enseignement moral et civique",
        "Accompagnement personnalisé",
        "Accompagnement au choix de l'orientation",
    ],
    "Enseignements de spécialité (EDS)": [
        "Arts",
        "Biologie-écologie",
        "Éducation physique, pratiques et culture sportives",
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
    "Options — Terminale uniquement": [
        "Mathématiques complémentaires",
        "Mathématiques expertes",
        "Droits et grands enjeux du monde contemporain",
    ],
    "Options — 1ère et/ou Terminale": [
        "Langue vivante C",
        "LCA : latin",
        "LCA : grec",
        "Éducation physique et sportive",
        "Arts",
        "Langue des signes française",
        "Hippologie et équitation",
        "Agronomie, économie, territoires",
        "Pratiques sociales et culturelles",
    ],
    "Épreuves et orientation": [
        "Grand Oral",
        "Aide à l'orientation",
    ],
}

NIVEAUX = ["Seconde", "Première", "Terminale", "Première et Terminale", "Tous niveaux"]

TYPES_RESSOURCE = [
    "Cours",
    "Exercices",
    "Corrigé",
    "Annale",
    "Fiche de révision",
    "Méthodologie",
    "Sujet type bac",
    "Ressource pédagogique",
    "Lien web",
    "Vidéo éducative",
    "Document officiel",
    "Autre",
    "Divers",
]

# Collections consultées automatiquement sur toute requête "Toutes"
ALL_COLLECTIONS = [
    "rag_francais_premiere",
    "rag_maths_premiere",
    "rag_education",
    "rag_web3",
    "rag_divers",
]

WEB3_CATEGORIES = [
    "Blockchain fondamentaux",
    "Solana",
    "Ethereum",
    "Smart Contracts",
    "DeFi",
    "NFT",
    "Tokenomics",
    "Sécurité Web3",
    "Développement dApp",
    "Anchor Framework",
    "Rust / Move",
    "Wallets & Identité",
    "DAO & Gouvernance",
    "Layer 2 & Scaling",
    "Autre Web3",
]


# ═══════════════════════════════════════════════════════════════
# HELPERS API
# ═══════════════════════════════════════════════════════════════

def _headers_json() -> dict[str, str]:
    """Headers pour requêtes JSON."""
    return {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}


def _headers_upload() -> dict[str, str]:
    """Headers pour uploads multipart."""
    return {"Authorization": f"Bearer {API_TOKEN}"}


def api_get(endpoint: str, timeout: float = 60.0) -> dict[str, Any] | None:
    """GET vers l'API RAG."""
    try:
        resp = httpx.get(f"{API_BASE}{endpoint}", headers=_headers_json(), timeout=timeout)
        if resp.status_code == 200:
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Connexion API échouée: {exc}")
    return None


def api_post(endpoint: str, data: dict[str, Any], timeout: float = 60.0) -> dict[str, Any] | None:
    """POST JSON vers l'API RAG."""
    try:
        resp = httpx.post(f"{API_BASE}{endpoint}", json=data, headers=_headers_json(), timeout=timeout)
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Connexion API échouée: {exc}")
    return None


def _build_search_payload(
    *,
    query: str,
    k: int,
    collection: str,
    section: str,
    filters: dict[str, Any],
    score_threshold: float | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"q": query, "k": k}
    if collection:
        payload["collection"] = collection
    elif section and section != "all":
        payload["section"] = section
    if filters:
        payload["filters"] = filters
    if score_threshold is not None:
        payload["score_threshold"] = score_threshold
    return payload


def api_upload(
    endpoint: str,
    files: list[tuple[str, bytes, str]],
    params: dict[str, str] | None = None,
    timeout: float = 900.0,
) -> dict[str, Any] | None:
    """Upload multipart vers l'API RAG."""
    try:
        multipart = [("files", (n, c, m)) for n, c, m in files]
        resp = httpx.post(
            f"{API_BASE}{endpoint}", files=multipart,
            params=params or {}, headers=_headers_upload(), timeout=timeout,
        )
        if resp.status_code in (200, 202):
            from typing import cast
            return cast(dict[str, Any], resp.json())
        st.error(f"API {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        st.error(f"Upload échoué: {exc}")
    return None


# ═══════════════════════════════════════════════════════════════
# COMPOSANTS RÉUTILISABLES
# ═══════════════════════════════════════════════════════════════

def _show_ingest_result(result: dict[str, Any] | None) -> None:
    """Affiche le résultat d'une ingestion."""
    if not result:
        return
    added = result.get("total_added", 0)
    skipped = result.get("total_skipped", 0)
    if added > 0:
        st.success(f"✅ {added} chunk(s) ajouté(s), {skipped} doublon(s) ignoré(s)")
    elif skipped > 0:
        st.warning(f"⚠️ Tous les contenus étaient déjà ingérés ({skipped} doublons)")
    else:
        st.info("Aucun contenu éligible à l'ingestion.")
    for item in result.get("results", []):
        icon = {"ok": "✅", "duplicate": "⚠️", "empty": "⬜", "error": "❌"}.get(item.get("status", ""), "❓")
        name = item.get("filename", item.get("url", "?"))
        st.caption(f"{icon} **{name}** — {item.get('status', '?')} (ajoutés: {item.get('added', 0)})")


def _render_upload_tab(metadata: dict[str, str], key_prefix: str) -> None:
    """Onglet Upload de fichiers réutilisable avec upload fichier par fichier."""
    st.markdown("**Formats** : PDF, DOCX, Markdown, TXT, HTML, images (OCR), audio, vidéo")
    uploaded = st.file_uploader(
        "Glissez-déposez vos fichiers",
        type=["pdf", "docx", "doc", "md", "txt", "csv", "html", "htm",
              "jpg", "jpeg", "png", "gif", "bmp", "webp",
              "mp3", "wav", "m4a", "mp4", "avi", "mkv"],
        accept_multiple_files=True,
        key=f"{key_prefix}_files",
    )
    if uploaded:
        st.info(f"{len(uploaded)} fichier(s) sélectionné(s)")
        rows = [{"Nom": f.name, "Taille": f"{f.size / 1024:.1f} Ko", "Type": f.type or "?"} for f in uploaded]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if st.button("🚀 Ingérer les fichiers", key=f"{key_prefix}_btn"):
            total_files = len(uploaded)
            total_added = 0
            total_duplicates = 0
            total_errors = 0
            file_results: list[Any] = []
            
            progress_bar = st.progress(0, text="Préparation...")
            status_container = st.container()
            
            for idx, f in enumerate(uploaded):
                progress = (idx + 1) / total_files
                progress_bar.progress(progress, text=f"Fichier {idx + 1}/{total_files}")
                
                with status_container:
                    st.text(f"📤 {f.name}...")
                
                payload = [(f.name, f.read(), f.type or "application/octet-stream")]
                result = api_upload("/ingest/upload-files", payload, params={"metadata": json.dumps(metadata)}, timeout=300.0)
                
                if result:
                    items = result.get("results", [])
                    item = items[0] if items else {}
                    added = int(result.get("total_added", item.get("added", 0) or 0) or 0)
                    skipped = int(result.get("total_skipped", item.get("skipped", 0) or 0) or 0)
                    detail = str(item.get("detail", "") or "")
                    status = str(item.get("status", "") or "")
                    if not status:
                        status = "ok" if added > 0 else ("duplicate" if skipped > 0 else "error")
                    total_added += added
                    total_duplicates += skipped
                    if status == "error":
                        total_errors += 1
                    file_results.append((f.name, status, added, skipped, detail))
                else:
                    total_errors += 1
                    file_results.append((f.name, "timeout", 0, 0, "Aucune réponse de l'API"))
            
            progress_bar.progress(1.0, text="Terminé !")
            
            # Summary
            if total_added > 0:
                st.success(f"✅ {total_added} chunk(s) ajouté(s)")
            if total_duplicates > 0:
                st.warning(f"⚠️ {total_duplicates} doublon(s) ignoré(s)")
            if total_errors > 0:
                st.error(f"❌ {total_errors} erreur(s)")
            
            # Per-file details
            with st.expander("📋 Détails par fichier"):
                for fr in file_results:
                    # Support both old tuple format and new dict format
                    if isinstance(fr, dict):
                        name = fr.get("name", "?")
                        status = fr.get("status", "?")
                        added = fr.get("added", 0)
                        skipped = fr.get("skipped", 0)
                        detail = fr.get("detail", "")
                    else:
                        # Legacy tuple format: (name, status, added)
                        if len(fr) >= 3:
                            name, status, added = fr[:3]
                        else:
                            name, status = fr[:2]
                            added = 0
                        skipped = 0
                        detail = ""
                    icon = {
                        "ok": "✅", "empty": "⬜", "error": "❌", "duplicate": "⚠️", "unsupported": "⏭️", "invalid": "⚠️",
                    }.get(status, "❓")
                    if status == "ok" and added > 0:
                        st.caption(f"{icon} **{name}** — {status} (ajoutés: {added})")
                    elif status in {"duplicate", "unsupported", "invalid"} and skipped > 0:
                        st.caption(f"{icon} **{name}** — {status} (ignorés: {skipped})")
                    elif status == "error":
                        st.caption(f"{icon} **{name}** — {status} ({detail})")
                    else:
                        st.caption(f"{icon} **{name}** — {status}")


def _render_urls_tab(metadata: dict[str, str], key_prefix: str) -> None:
    """Onglet ingestion par URLs réutilisable avec traitement URL par URL."""
    st.markdown("Une URL par ligne. Les doublons sont automatiquement détectés.")
    urls_text = st.text_area(
        "URLs", height=180,
        placeholder="https://eduscol.education.fr/...\nhttps://docs.solana.com/...",
        key=f"{key_prefix}_urls",
    )
    if urls_text.strip():
        urls = [u.strip() for u in urls_text.strip().splitlines() if u.strip()]
        st.info(f"{len(urls)} URL(s)")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Vérifier doublons", key=f"{key_prefix}_chk"):
                section = metadata.get("section", "education")
                with st.spinner("Vérification..."):
                    r = api_post("/ingest/check-duplicates", {"sources": urls, "section": section, "collection": metadata.get("collection", "")})
                if r:
                    for it in r.get("results", []):
                        icon = "⚠️ Existant" if it.get("already_ingested") else "✅ Nouveau"
                        st.caption(f"{icon} — `{it.get('source', '?')}`")
        with c2:
            if st.button("🚀 Ingérer les URLs", key=f"{key_prefix}_go"):
                total_urls = len(urls)
                total_added = 0
                total_skipped = 0
                total_errors = 0
                url_results: list[tuple[str, str, int]] = []
                
                progress_bar = st.progress(0, text="Préparation...")
                
                for idx, url in enumerate(urls):
                    progress = (idx + 1) / total_urls
                    progress_bar.progress(progress, text=f"URL {idx + 1}/{total_urls}")
                    
                    result = api_post("/ingest/urls", {"urls": [url], "metadata": metadata}, timeout=120.0)
                    
                    if result:
                        added = result.get("total_added", 0)
                        skipped = result.get("total_skipped", 0)
                        total_added += added
                        total_skipped += skipped
                        status = "ok" if added > 0 else ("duplicate" if skipped > 0 else "empty")
                        url_results.append((url, status, added))
                    else:
                        total_errors += 1
                        url_results.append((url, "timeout", 0))
                
                progress_bar.progress(1.0, text="Terminé !")
                
                # Summary
                if total_added > 0:
                    st.success(f"✅ {total_added} chunk(s) ajouté(s)")
                if total_skipped > 0:
                    st.warning(f"⚠️ {total_skipped} doublon(s) ignoré(s)")
                if total_errors > 0:
                    st.error(f"❌ {total_errors} erreur(s)/timeout(s)")
                
                # Per-URL details
                with st.expander("📋 Détails par URL"):
                    for url, status, added in url_results:
                        icon = {"ok": "✅", "duplicate": "⚠️", "empty": "⬜", "timeout": "⏱️"}.get(status, "❓")
                        st.caption(f"{icon} **{url[:60]}...** — {status} (ajoutés: {added})")


def _render_drive_tab(metadata: dict[str, str], key_prefix: str) -> None:
    """Onglet ingestion Google Drive avec suivi de progression en temps réel."""
    st.markdown(
        "Entrez l'ID du dossier Google Drive. "
        "Les fichiers déjà ingérés ou non modifiés seront ignorés."
    )
    folder_id = st.text_input(
        "ID du dossier Drive",
        placeholder="1ABC2DEF3GHI4JKL5MNO...",
        key=f"{key_prefix}_drive",
        help="ID visible dans l'URL : drive.google.com/drive/folders/**<ID>**",
    )

    if folder_id.strip() and st.button("☁️ Lancer l'ingestion Drive", key=f"{key_prefix}_drv_btn"):
        # Lancer l'ingestion et récupérer le task_id
        result = api_post("/ingest/drive", {"folder_id": folder_id.strip(), "metadata": metadata}, timeout=30.0)
        if not result or "task_id" not in result:
            st.error(f"Erreur lors du lancement : {result}")
            return

        task_id = result["task_id"]
        target_col = result.get("target_collection", "?")

        st.info(f"📂 Collection cible : **`{target_col}`**")

        # Conteneurs pour la progression dynamique
        status_text = st.empty()
        progress_bar = st.progress(0)
        metrics_row = st.empty()
        current_file_text = st.empty()
        file_results_container = st.container()

        # Polling de la progression
        while True:
            time.sleep(2)
            try:
                status_resp = api_get(f"/ingest/drive/status/{task_id}", timeout=10.0)
            except Exception:
                status_resp = None

            if not status_resp:
                status_text.warning("⏳ En attente de réponse du serveur...")
                continue

            task_status = status_resp.get("status", "pending")
            total = status_resp.get("total_files", 0)
            processed = status_resp.get("processed_files", 0)
            added = status_resp.get("added_chunks", 0)
            skipped = status_resp.get("skipped_files", 0)
            errors = status_resp.get("error_files", 0)
            current = status_resp.get("current_file", "")
            progress_pct = status_resp.get("progress_pct", 0)
            elapsed = status_resp.get("elapsed_seconds", 0)

            # Mise à jour de la barre de progression
            progress_bar.progress(min(progress_pct, 100))

            # Statut textuel
            status_labels = {
                "pending": "⏳ En attente...",
                "scanning": "🔍 Scan du dossier Drive en cours...",
                "ingesting": f"⚙️ Ingestion en cours — {processed}/{total} fichier(s)",
                "done": f"✅ Terminé — {processed}/{total} fichier(s) traité(s)",
                "error": f"❌ Erreur : {status_resp.get('error_message', '?')}",
            }
            status_text.markdown(f"**{status_labels.get(task_status, task_status)}**")

            # Métriques
            if total > 0:
                m1, m2, m3, m4 = metrics_row.columns(4)
                m1.metric("Fichiers traités", f"{processed}/{total}")
                m2.metric("Chunks ajoutés", added)
                m3.metric("Ignorés", skipped)
                m4.metric("Erreurs", errors)

            # Fichier en cours
            if current and task_status == "ingesting":
                current_file_text.caption(f"📄 En cours : `{current}`")
            else:
                current_file_text.empty()

            # Terminé ou erreur → sortir de la boucle
            if task_status in ("done", "error"):
                progress_bar.progress(100 if task_status == "done" else progress_pct)

                # Résumé final
                st.markdown("---")
                if task_status == "done":
                    st.success(
                        f"✅ Ingestion terminée en **{elapsed:.1f}s** — "
                        f"**{added}** chunks ajoutés, **{skipped}** fichier(s) ignoré(s), **{errors}** erreur(s) dans `{target_col}`"
                    )
                else:
                    st.error(f"❌ Ingestion échouée : {status_resp.get('error_message', '?')}")

                # Détail fichier par fichier
                file_results = status_resp.get("file_results", [])
                if file_results:
                    with file_results_container.expander(
                        f"📋 Détail des {len(file_results)} fichier(s)", expanded=False
                    ):
                        for fr in file_results:
                            icon = {
                                "ok": "✅", "empty": "⬜", "error": "❌", "duplicate": "⚠️", "unsupported": "⏭️", "invalid": "⚠️",
                            }.get(fr.get("status", ""), "❓")
                            name = fr.get("name", "?")
                            detail = ""
                            if fr.get("added"):
                                detail = f" — {fr['added']} chunks ajoutés"
                                if fr.get("skipped"):
                                    detail += f", {fr['skipped']} ignorés"
                            elif fr.get("skipped"):
                                detail = f" — {fr['skipped']} doublon(s) ignoré(s)"
                            elif fr.get("detail"):
                                detail = f" — {fr['detail'][:80]}"
                            st.caption(f"{icon} **{name}**{detail}")
                break


# ═══════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
# ═══════════════════════════════════════════════════════════════

st.sidebar.image("https://img.icons8.com/fluency/96/brain.png", width=60)
st.sidebar.title("RAG Nexus Réussite")

page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "🎓 Éducation",
        "� Maths 1ère",
        "�🔗 Web3 & Blockchain",
        "📦 Divers",
        "🔍 Recherche",
        "🔧 Administration",
    ],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.caption(f"API : `{API_BASE}`")


# ═══════════════════════════════════════════════════════════════
# PAGE DASHBOARD
# ═══════════════════════════════════════════════════════════════
if page == "📊 Dashboard":
    st.title("📊 Dashboard RAG — Vue d'ensemble")

    # Charger les collections
    cols_data = api_get("/collections")
    if cols_data:
        collections = cols_data.get("collections", [])
        if collections:
            metrics_cols = st.columns(len(collections) + 1)
            total_docs = 0
            for i, col_info in enumerate(collections):
                name = col_info.get("name", "?")
                count = col_info.get("count", 0)
                total_docs += count
                label = (
                    "📚 Français 1ère" if name == "rag_francais_premiere"
                    else "📐 Maths 1ère" if name == "rag_maths_premiere"
                    else "🎓 Éducation" if "education" in name
                    else "🔗 Web3" if "web3" in name
                    else "📦 Divers" if "divers" in name
                    else name
                )
                metrics_cols[i].metric(label, f"{count} chunks")
            metrics_cols[-1].metric("📦 Total", f"{total_docs} chunks")

            st.markdown("---")

            # Détails par collection
            for col_info in collections:
                name = col_info.get("name", "?")
                stats = api_get(f"/stats/{name}")
                if stats:
                    section_label = (
                        "📚 Français 1ère" if name == "rag_francais_premiere"
                        else "📐 Maths 1ère" if name == "rag_maths_premiere"
                        else "🎓 Éducation" if "education" in name
                        else "🔗 Web3" if "web3" in name
                        else "📦 Divers" if "divers" in name
                        else name
                    )
                    with st.expander(f"{section_label} — `{name}` ({stats.get('doc_count', 0)} chunks)", expanded=True):
                        c1, c2 = st.columns(2)
                        c1.write(f"**Modèle d'embedding** : `{stats.get('embed_model', '?')}`")
                        c2.write(f"**Chunks** : {stats.get('doc_count', 0)}")
                        if stats.get("matieres"):
                            st.write(f"**Matières indexées** : {', '.join(stats['matieres'])}")
                        if stats.get("niveaux"):
                            st.write(f"**Niveaux** : {', '.join(stats['niveaux'])}")
                        if stats.get("groupes"):
                            st.write(f"**Groupes** : {', '.join(stats['groupes'])}")
                        if stats.get("types_ressource"):
                            st.write(f"**Types** : {', '.join(stats['types_ressource'])}")
        else:
            st.info("Aucune collection créée. Commencez par ingérer des documents.")
    else:
        st.warning("Impossible de charger les collections. Vérifiez la connexion API.")

    # Santé
    st.markdown("---")
    health = api_get("/health")
    if health:
        st.success("✅ API opérationnelle")
    else:
        st.error("❌ API non joignable")


# ═══════════════════════════════════════════════════════════════
# PAGE ÉDUCATION
# ═══════════════════════════════════════════════════════════════
elif page == "🎓 Éducation":
    st.title("🎓 Éducation — Accompagnement scolaire")
    st.markdown(
        "Ingérez et organisez des ressources pédagogiques par matière, niveau et type. "
        "Choisissez explicitement la collection cible pour refléter la structure réelle du RAG. "
        "Par défaut, les contenus de Français Première sont envoyés dans **`rag_francais_premiere`**."
    )

    # ── Sélection catégorie / matière / niveau / type ──
    st.subheader("📂 Classification de la ressource")

    col_g, col_m = st.columns(2)
    with col_g:
        groupe = st.selectbox("Groupe d'enseignement", list(EDUCATION_TAXONOMY.keys()))
    with col_m:
        matiere = st.selectbox("Matière", EDUCATION_TAXONOMY.get(groupe, []))

    col_n, col_t = st.columns(2)
    with col_n:
        niveau = st.selectbox("Niveau", NIVEAUX)
    with col_t:
        type_ressource = st.selectbox("Type de ressource", TYPES_RESSOURCE)

    collection_education = st.selectbox(
        "Collection cible",
        ["rag_francais_premiere", "rag_maths_premiere", "rag_education"],
        index=0,
        help="`rag_francais_premiere` : Français 1ère | `rag_maths_premiere` : Maths 1ère spécialité | `rag_education` : corpus général",
    )

    st.markdown("---")

    edu_meta = {
        "section": "education",
        "collection": collection_education,
        "groupe": groupe,
        "matiere": matiere,
        "niveau": niveau,
        "type_ressource": type_ressource,
    }

    # ── Onglets d'ingestion ──
    tab_up, tab_url, tab_drv = st.tabs(["📁 Upload fichiers", "🔗 URLs", "☁️ Google Drive"])
    with tab_up:
        _render_upload_tab(edu_meta, "edu")
    with tab_url:
        _render_urls_tab(edu_meta, "edu")
    with tab_drv:
        _render_drive_tab(edu_meta, "edu")

    # ── Statistiques collection éducation ──
    st.markdown("---")
    with st.expander(f"📊 Statistiques collection {collection_education}", expanded=False):
        stats = api_get(f"/stats/{collection_education}")
        if stats:
            c1, c2, c3 = st.columns(3)
            c1.metric("Chunks", stats.get("doc_count", 0))
            c2.metric("Matières", len(stats.get("matieres", [])))
            c3.metric("Embedding", stats.get("embed_model", "?"))
            if stats.get("matieres"):
                st.write(f"**Matières** : {', '.join(stats['matieres'])}")

    # ── Référentiel ──
    with st.expander("📋 Référentiel complet des enseignements", expanded=False):
        for g, items in EDUCATION_TAXONOMY.items():
            st.markdown(f"**{g}**")
            for it in items:
                st.caption(f"  • {it}")


# ═══════════════════════════════════════════════════════════════
# PAGE MATHS 1ÈRE
# ═══════════════════════════════════════════════════════════════
elif page == "📐 Maths 1ère":
    st.title("📐 Maths Première — Spécialité")
    maths_stats = api_get("/stats/rag_maths_premiere") or {}
    maths_fallback_active = maths_stats.get("doc_count", 0) == 0
    st.markdown(
        "Collection dédiée **Mathématiques Première** (spécialité). "
        "Les nouveaux documents ingérés ici sont indexés dans **`rag_maths_premiere`**."
    )
    if maths_fallback_active:
        st.warning(
            "La collection dédiée est actuellement vide. Les recherches **Maths 1ère** "
            "basculent temporairement sur **`rag_education`** avec les filtres "
            "`Mathématiques / Première / Enseignements de spécialité (EDS)`."
        )
    else:
        st.info(
            "La recherche **Maths 1ère** utilise la collection dédiée "
            "**`rag_maths_premiere`**."
        )

    st.subheader("📂 Type de ressource")
    col_t, col_d = st.columns(2)
    with col_t:
        maths_type = st.selectbox(
            "Type de ressource",
            TYPES_RESSOURCE,
            index=TYPES_RESSOURCE.index("Exercices"),
            key="maths_type",
        )
    with col_d:
        maths_tag = st.text_input(
            "Tag libre (optionnel)",
            placeholder="ex: suites, second degré, probabilités…",
            key="maths_tag",
        )

    st.markdown("---")

    maths_meta: dict[str, str] = {
        "section": "maths_premiere",
        "collection": "rag_maths_premiere",
        "matiere": "Mathématiques",
        "niveau": "Première",
        "groupe": "Enseignements de spécialité (EDS)",
        "type_ressource": maths_type,
    }
    if maths_tag.strip():
        maths_meta["tag"] = maths_tag.strip()

    tab_up, tab_url, tab_drv = st.tabs(["📁 Upload fichiers", "🔗 URLs", "☁️ Google Drive"])
    with tab_up:
        _render_upload_tab(maths_meta, "maths")
    with tab_url:
        _render_urls_tab(maths_meta, "maths")
    with tab_drv:
        _render_drive_tab(maths_meta, "maths")

    st.markdown("---")
    with st.expander("📊 Statistiques collection Maths 1ère", expanded=False):
        if maths_stats:
            c1, c2, c3 = st.columns(3)
            c1.metric("Chunks", maths_stats.get("doc_count", 0))
            c2.metric("Types", len(maths_stats.get("types_ressource", [])))
            c3.metric("Embedding", maths_stats.get("embed_model", "?"))
            if maths_stats.get("types_ressource"):
                st.write(f"**Types** : {', '.join(maths_stats['types_ressource'])}")
            if maths_fallback_active:
                st.caption(
                    "Fallback actif: la recherche Maths 1ère est servie par "
                    "`rag_education` avec filtres métier tant que cette collection reste vide."
                )


# ═══════════════════════════════════════════════════════════════
# PAGE DIVERS
# ═══════════════════════════════════════════════════════════════
elif page == "📦 Divers":
    st.title("📦 Divers — Ressources variées")
    st.markdown(
        "Ingérez ici des ressources de **types variés** sans catégorisation stricte. "
        "Cette collection (**`rag_divers`**) est **consultée automatiquement** "
        "lors de toute recherche multi-collection (mode *Toutes*). "
        "Utile pour des documents transversaux, notes internes, références générales."
    )

    st.subheader("📂 Classification optionnelle")
    col_t, col_d = st.columns(2)
    with col_t:
        divers_type = st.selectbox(
            "Type de ressource",
            TYPES_RESSOURCE,
            index=TYPES_RESSOURCE.index("Divers"),
            key="divers_type",
        )
    with col_d:
        divers_tag = st.text_input(
            "Tag libre (optionnel)",
            placeholder="ex: concours, orientation, transversal…",
            key="divers_tag",
        )

    st.markdown("---")

    divers_meta: dict[str, str] = {
        "section": "divers",
        "collection": "rag_divers",
        "type_ressource": divers_type,
    }
    if divers_tag.strip():
        divers_meta["tag"] = divers_tag.strip()

    tab_up, tab_url, tab_drv = st.tabs(["📁 Upload fichiers", "🔗 URLs", "☁️ Google Drive"])
    with tab_up:
        _render_upload_tab(divers_meta, "div")
    with tab_url:
        _render_urls_tab(divers_meta, "div")
    with tab_drv:
        _render_drive_tab(divers_meta, "div")

    st.markdown("---")
    with st.expander("📊 Statistiques collection Divers", expanded=False):
        stats = api_get("/stats/rag_divers")
        if stats:
            c1, c2 = st.columns(2)
            c1.metric("Chunks", stats.get("doc_count", 0))
            c2.metric("Embedding", stats.get("embed_model", "?"))
            if stats.get("types_ressource"):
                st.write(f"**Types** : {', '.join(stats['types_ressource'])}")


# ═══════════════════════════════════════════════════════════════
# PAGE WEB3 & BLOCKCHAIN
# ═══════════════════════════════════════════════════════════════
elif page == "🔗 Web3 & Blockchain":
    st.title("🔗 Web3 & Blockchain")
    st.markdown(
        "Ingérez de la documentation Web3 : blockchain, DeFi, NFT, Solana, smart-contracts. "
        "Collection cible : **`rag_web3`**."
    )

    st.subheader("📂 Classification")
    col_cat, col_type = st.columns(2)
    with col_cat:
        web3_cat = st.selectbox("Catégorie Web3", WEB3_CATEGORIES)
    with col_type:
        web3_type = st.selectbox("Type de ressource", [
            "Documentation officielle",
            "Tutoriel",
            "Article technique",
            "Whitepaper",
            "Code / Snippet",
            "Guide développeur",
            "Audit de sécurité",
            "Autre",
        ], key="web3_type")

    st.markdown("---")

    web3_meta = {
        "section": "web3",
        "categorie": web3_cat,
        "type_ressource": web3_type,
    }

    tab_up, tab_url, tab_drv = st.tabs(["📁 Upload fichiers", "🔗 URLs", "☁️ Google Drive"])
    with tab_up:
        _render_upload_tab(web3_meta, "web3")
    with tab_url:
        _render_urls_tab(web3_meta, "web3")
    with tab_drv:
        _render_drive_tab(web3_meta, "web3")

    # Stats Web3
    st.markdown("---")
    with st.expander("📊 Statistiques collection Web3", expanded=False):
        stats = api_get("/stats/rag_web3")
        if stats:
            c1, c2 = st.columns(2)
            c1.metric("Chunks", stats.get("doc_count", 0))
            c2.metric("Embedding", stats.get("embed_model", "?"))


# ═══════════════════════════════════════════════════════════════
# PAGE RECHERCHE
# ═══════════════════════════════════════════════════════════════
elif page == "🔍 Recherche":
    st.title("🔍 Recherche RAG")

    # Section ciblée
    search_section = st.radio(
        "Collection cible",
        ["📚 Français Première", "📐 Maths 1ère", "🎓 Éducation", "🔗 Web3", "📦 Divers", "📦 Toutes"],
        horizontal=True,
    )

    query = st.text_input("Question", placeholder="Qu'est-ce qu'un smart contract ?")
    k = st.slider("Nombre de résultats", 1, 20, 6)
    use_score_threshold = st.checkbox("Activer un seuil de distance", value=True)
    score_threshold = st.slider(
        "Distance max",
        min_value=0.0,
        max_value=2.0,
        value=0.55,
        step=0.05,
        disabled=not use_score_threshold,
    )

    # Filtres contextuels
    filters: dict[str, Any] = {}
    collection_key = ""
    if search_section == "📚 Français Première":
        section_key = "education"
        collection_key = "rag_francais_premiere"
        with st.expander("🔧 Filtres avancés", expanded=False):
            all_matieres = []
            for items in EDUCATION_TAXONOMY.values():
                all_matieres.extend(items)
            f_matiere = st.selectbox("Matière", ["Tous"] + sorted(set(all_matieres)), key="s_mat_fp")
            f_niveau = st.selectbox("Niveau", ["Tous"] + NIVEAUX, key="s_niv_fp")
            f_type = st.selectbox("Type", ["Tous"] + TYPES_RESSOURCE, key="s_type_fp")
            if f_matiere != "Tous":
                filters["matiere"] = f_matiere
            if f_niveau != "Tous":
                filters["niveau"] = f_niveau
            if f_type != "Tous":
                filters["type_ressource"] = f_type
    elif search_section == "📐 Maths 1ère":
        section_key = "maths_premiere"
        collection_key = ""
        st.caption(
            "Recherche ciblée Maths 1ère. Si la collection dédiée est vide, "
            "l'API bascule automatiquement sur `rag_education` avec les filtres adéquats."
        )
    elif search_section == "🎓 Éducation":
        section_key = "education"
        collection_key = "rag_education"
        with st.expander("🔧 Filtres avancés", expanded=False):
            all_matieres = []
            for items in EDUCATION_TAXONOMY.values():
                all_matieres.extend(items)
            f_matiere = st.selectbox("Matière", ["Tous"] + sorted(set(all_matieres)), key="s_mat")
            f_niveau = st.selectbox("Niveau", ["Tous"] + NIVEAUX, key="s_niv")
            f_type = st.selectbox("Type", ["Tous"] + TYPES_RESSOURCE, key="s_type")
            if f_matiere != "Tous":
                filters["matiere"] = f_matiere
            if f_niveau != "Tous":
                filters["niveau"] = f_niveau
            if f_type != "Tous":
                filters["type_ressource"] = f_type
    elif search_section == "🔗 Web3":
        section_key = "web3"
        collection_key = ""
        with st.expander("🔧 Filtres avancés", expanded=False):
            f_cat = st.selectbox("Catégorie", ["Tous"] + WEB3_CATEGORIES, key="s_w3cat")
            if f_cat != "Tous":
                filters["categorie"] = f_cat
    elif search_section == "📦 Divers":
        section_key = "divers"
        collection_key = "rag_divers"
    else:
        section_key = "all"
        collection_key = ""

    if query and st.button("🔎 Rechercher"):
        with st.spinner("Recherche en cours..."):
            if section_key == "all":
                # Recherche multi-collection : interroge chaque collection et fusionne par score
                all_hits: list[dict[str, Any]] = []
                searched_cols: list[str] = []
                for col_name in ALL_COLLECTIONS:
                    search_collection = col_name
                    search_section = ""
                    if col_name == "rag_maths_premiere":
                        search_collection = ""
                        search_section = "maths_premiere"
                    payload_col = _build_search_payload(
                        query=query,
                        k=k,
                        collection=search_collection,
                        section=search_section,
                        filters={},
                        score_threshold=score_threshold if use_score_threshold else None,
                    )
                    r = api_post("/search", payload_col, timeout=60.0)
                    if r and r.get("hits"):
                        for h in r["hits"]:
                            h["_collection"] = col_name
                        all_hits.extend(r["hits"])
                        searched_cols.append(col_name)
                deduped_hits: dict[str, dict[str, Any]] = {}
                for hit in all_hits:
                    meta = hit.get("metadata", {})
                    dedupe_key = str(
                        meta.get("sha256")
                        or hit.get("id")
                        or meta.get("source")
                        or ""
                    ).strip()
                    if not dedupe_key:
                        dedupe_key = f"anon-{len(deduped_hits)}"
                    current = deduped_hits.get(dedupe_key)
                    if current is None or hit.get("score", 1.0) < current.get("score", 1.0):
                        deduped_hits[dedupe_key] = hit
                # Trier par score ascendant (distance cosinus — plus petit = meilleur)
                merged_hits = sorted(deduped_hits.values(), key=lambda h: h.get("score", 1.0))[:k]
                result: dict[str, Any] | None = {
                    "hits": merged_hits,
                    "collection": "toutes (" + ", ".join(searched_cols) + ")",
                }
            else:
                payload = _build_search_payload(
                    query=query,
                    k=k,
                    collection=collection_key,
                    section=section_key,
                    filters=filters,
                    score_threshold=score_threshold if use_score_threshold else None,
                )
                result = api_post("/search", payload, timeout=60.0)

        if result:
            hits = result.get("hits", [])
            st.info(f"{len(hits)} résultat(s) dans `{result.get('collection', '?')}`")

            for i, h in enumerate(hits):
                h_col = h.pop("_collection", None)
                score = h.get("score", 0)
                meta = h.get("metadata", {})
                source = meta.get("source", meta.get("original_filename", "Sans titre"))
                matiere_tag = f" | 📚 {meta['matiere']}" if meta.get("matiere") else ""
                niveau_tag = f" | 🎯 {meta['niveau']}" if meta.get("niveau") else ""
                cat_tag = f" | 🏷️ {meta['categorie']}" if meta.get("categorie") else ""
                col_tag = f" | 🗄️ {h_col}" if h_col else ""

                with st.expander(f"#{i+1} — {source} (score: {score:.4f}{matiere_tag}{niveau_tag}{cat_tag}{col_tag})"):
                    doc_text = h.get("document", "")
                    if doc_text:
                        st.markdown(doc_text[:2000])
                        if len(doc_text) > 2000:
                            st.caption("... (tronqué)")
                    st.caption(f"**Métadonnées** : {json.dumps(meta, ensure_ascii=False, indent=2)}")


# ═══════════════════════════════════════════════════════════════
# PAGE ADMINISTRATION
# ═══════════════════════════════════════════════════════════════
elif page == "🔧 Administration":
    st.title("🔧 Administration")

    # Santé API
    st.subheader("🏥 Santé du service")
    health = api_get("/health")
    if health:
        st.success(f"✅ API opérationnelle — statut : {health.get('status', '?')}")
    else:
        st.error("❌ API non joignable")

    # Collections
    st.subheader("📦 Collections ChromaDB")
    cols_data = api_get("/collections")
    if cols_data:
        for c in cols_data.get("collections", []):
            st.write(f"- **`{c.get('name')}`** : {c.get('count', 0)} chunks")

    # Référentiel éducation complet
    st.subheader("📋 Référentiel Éducation")
    with st.expander("Voir toutes les matières et catégories"):
        for g, items in EDUCATION_TAXONOMY.items():
            st.markdown(f"**{g}**")
            for it in items:
                st.write(f"  - {it}")

    st.subheader("📋 Catégories Web3")
    with st.expander("Voir toutes les catégories Web3"):
        for cat in WEB3_CATEGORIES:
            st.write(f"  - {cat}")
