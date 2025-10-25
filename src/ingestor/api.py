# Fichier: /srv/rag/ingestor/api.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal, Dict
import os, hashlib, tempfile, requests

import chromadb
from langchain_community.document_loaders import WebBaseLoader, PyPDFLoader
from langchain_google_community import GoogleDriveLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
import docx
from langchain_core.documents import Document

# --- Configuration ---
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL  = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = "ressources_pedagogiques_terminale"

app = FastAPI(title="RAG Ingestor API")

# --- Modèle de requête ---
class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source_type: Literal["url", "gdrive_folder", "pdf", "docx"]
    source: str
    metadata_hints: Dict[str, str] = Field(default_factory=dict, alias="hints")

# --- Utilitaires ---
def normalize_metadata(d: Dict) -> Dict:
    return {str(k).strip().lower().replace(" ", "_"): v for k, v in d.items() if v not in (None, "")}

def get_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_docx(file_path: str):
    try:
        d = docx.Document(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le DOCX: {e}")
    texts = []
    for p in d.paragraphs:
        if p.text and p.text.strip():
            texts.append(p.text.strip())
    # (option simple; on pourra enrichir avec les tableaux si besoin)
    content = "\n".join(texts).strip()
    if not content:
        return []
    return [Document(page_content=content, metadata={"source": os.path.basename(file_path)})]

def load_from_url(url: str):
    if url.lower().endswith(".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                tmp.write(r.content)
                tmp_path = tmp.name
            except requests.RequestException as e:
                raise HTTPException(status_code=400, detail=f"Échec du téléchargement PDF: {e}")
        try:
            docs = PyPDFLoader(tmp_path).load()
        finally:
            try: os.unlink(tmp_path)
            except Exception: pass
        return docs
    else:
        return WebBaseLoader(url).load()

# --- Endpoint ---
@app.post("/ingest")
def ingest_data(req: IngestRequest):
    # 1) Chargement
    try:
        if req.source_type == "url":
            docs = load_from_url(req.source)
        elif req.source_type == "gdrive_folder":
            loader = GoogleDriveLoader(folder_id=req.source, recursive=True)
            docs = loader.load()
        elif req.source_type == "pdf":
            docs = PyPDFLoader(req.source).load()
        elif req.source_type == "docx":
            docs = load_docx(req.source)
        else:
            raise HTTPException(status_code=400, detail=f"source_type non géré: {req.source_type}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de chargement: {e}")

    if not docs:
        return {"status": "ok", "message": "Aucun document chargé."}

    # 2) Découpage
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(docs)
    if not chunks:
        return {"status": "ok", "message": "Aucun chunk textuel après découpage."}

    # 3) Préparation
    ids, documents, metadatas = [], [], []
    for ch in chunks:
        text = (ch.page_content or "").strip()
        if not text:
            continue
        content_hash = get_content_hash(text)
        merged = {"sha256": content_hash, "source_type": req.source_type, "source": req.source}
        merged.update(ch.metadata or {})
        merged.update(req.metadata_hints or {})
        ids.append(content_hash)
        documents.append(text)
        metadatas.append(normalize_metadata(merged))

    if not ids:
        return {"status": "ok", "message": "Aucun contenu éligible à l'ingestion."}

    # 4) Insertion (avec déduplication par hash)
    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

        existing = collection.get(ids=ids)
        existing_ids = set(existing.get("ids", []))  # ids effectivement trouvés

        to_add_idx = [i for i, _id in enumerate(ids) if _id not in existing_ids]
        if not to_add_idx:
            return {"status": "ok", "added": 0, "skipped": len(ids)}

        emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
        docs_to_add = [documents[i] for i in to_add_idx]
        ids_to_add  = [ids[i] for i in to_add_idx]
        meta_to_add = [metadatas[i] for i in to_add_idx]
        embs_to_add = emb.embed_documents(docs_to_add)

        collection.add(documents=docs_to_add, ids=ids_to_add, metadatas=meta_to_add, embeddings=embs_to_add)
        return {"status": "ok", "added": len(ids_to_add), "skipped": len(existing_ids)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'ingestion dans ChromaDB: {e}")

@app.get("/health")
def health_check():
    return {"status": "healthy"}
