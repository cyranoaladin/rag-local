import streamlit as st, requests, pandas as pd, os
import chromadb

CHROMA_HOST = os.getenv("CHROMA_HOST","chroma")
CHROMA_PORT = int(os.getenv("CHROMA_PORT","8000"))
COLLECTION  = "ressources_pedagogiques_terminale"

st.set_page_config(layout="wide", page_title="Admin RAG Pédagogique")
st.title("Tableau de bord RAG")

st.header("1) Lancer une ingestion (via n8n)")
webhook = st.text_input("URL Webhook n8n (production)", "https://EXEMPLE.webhook.url/ingestion")
with st.form("ingest"):
    source = st.text_input("URL / ID GDrive / Chemin", "https://eduscol.education.fr/...")
    source_type = st.selectbox("Type", ["url","gdrive_folder","pdf","docx","py_dir"])
    c1,c2,c3 = st.columns(3)
    with c1:
        matiere = st.text_input("Matière","NSI"); voie = st.selectbox("Voie",["générale","technologique","commun"])
    with c2:
        niveau = st.selectbox("Niveau",["Première","Terminale"]); doc_type = st.selectbox("Doc type",["programme_officiel","annale_bac","cours","fiche_pedagogique"])
    with c3:
        annee = st.number_input("Année", min_value=2010, max_value=2035, value=2024)
    if st.form_submit_button("Envoyer"):
        if not webhook.startswith("http"):
            st.error("URL webhook invalide"); 
        else:
            payload = {"source":source, "source_type":source_type,
                       "hints":{"matiere":matiere,"voie":voie,"niveau":niveau,"document_type":doc_type,"annee_programme":annee}}
            try:
                r = requests.post(webhook, json=payload, timeout=30)
                st.success(f"n8n → {r.status_code}: {r.text[:200]}...")
            except Exception as e:
                st.error(f"Erreur webhook: {e}")

st.header("2) Explorer Chroma")
try:
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    col = client.get_or_create_collection(COLLECTION)
    st.info(f"Collection '{COLLECTION}' – {col.count()} documents")
    q = st.text_input("Requête sémantique", "définition de la dérivée (Terminale)")
    k = st.slider("Résultats", 1, 20, 5)
    if st.button("Rechercher"):
        res = col.query(query_texts=[q], n_results=k)
        if res and res.get("documents"):
            docs = res["documents"][0]; metas = res["metadatas"][0]; dists = res["distances"][0]
            for i, doc in enumerate(docs):
                with st.expander(f"Résultat #{i+1}  — distance {dists[i]:.4f}"):
                    st.text_area("Extrait", doc, height=200)
                    st.dataframe(pd.DataFrame(list(metas[i].items()), columns=["Champ","Valeur"]))
        else:
            st.warning("Aucun résultat.")
except Exception as e:
    st.error(f"Chroma indisponible: {e}")
