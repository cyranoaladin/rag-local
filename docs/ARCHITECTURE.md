# Architecture Diagrams — rag-local

Ce document contient les diagrammes d'architecture du projet rag-local.

## Sommaire

1. [Vue d'ensemble](#vue-densemble)
2. [Flux d'ingestion](#flux-dingestion)
3. [Flux de recherche](#flux-de-recherche)
4. [Architecture v2 (pgvector)](#architecture-v2-pgvector)
5. [Déploiement production](#déploiement-production)

---

## Vue d'ensemble

```mermaid
graph TB
    subgraph "Utilisateurs"
        UI[UI Streamlit]
        CLI[CLI / Scripts]
        N8N[n8n Workflows]
    end

    subgraph "Reverse Proxy"
        NGINX[Nginx + TLS]
    end

    subgraph "RAG Services"
        INGEST[Ingestor FastAPI]
        CHROMA[ChromaDB]
        OLLAMA[Ollama]
    end

    subgraph "Observabilité"
        PROM[Prometheus]
    end

    UI --> NGINX
    CLI --> NGINX
    N8N --> NGINX
    
    NGINX --> INGEST
    
    INGEST --> CHROMA
    INGEST --> OLLAMA
    
    INGEST --> PROM

    style NGINX fill:#4CAF50,color:#fff
    style INGEST fill:#2196F3,color:#fff
    style CHROMA fill:#FF9800,color:#fff
    style OLLAMA fill:#9C27B0,color:#fff
```

---

## Flux d'ingestion

```mermaid
sequenceDiagram
    participant C as Client
    participant N as Nginx
    participant I as Ingestor
    participant O as Ollama
    participant D as ChromaDB/pgvector

    C->>N: POST /ingest (JSON)
    N->>I: Forward request
    
    I->>I: Validate token & IP
    I->>I: Load source (URL/file/GDrive)
    
    I->>I: Chunk text (800/120)
    
    loop For each chunk
        I->>O: Generate embedding
        O-->>I: Vector (768 dims)
    end
    
    I->>I: Check duplicates (SHA256)
    I->>D: Upsert documents + embeddings
    D-->>I: OK
    
    I-->>N: 200 {status: ok, added: N}
    N-->>C: Response
```

---

## Flux de recherche

```mermaid
sequenceDiagram
    participant U as User
    participant S as Streamlit UI
    participant I as Ingestor
    participant D as ChromaDB/pgvector
    participant O as Ollama

    U->>S: Query text
    S->>I: POST /search {q, k}
    
    I->>O: Generate query embedding
    O-->>I: Vector (768 dims)
    
    I->>D: Query similar (top-k)
    D-->>I: Documents + metadata
    
    I-->>S: Results (JSON)
    S->>U: Display results
```

---

## Architecture v2 (pgvector)

```mermaid
graph TB
    subgraph "Clients"
        UI[UI Streamlit]
        CLI[CLI / API]
    end

    subgraph "API Layer"
        INGEST[Ingestor FastAPI]
        WORKER[Celery Worker]
    end

    subgraph "Data Layer"
        PG[(PostgreSQL<br/>pgvector)]
        REDIS[(Redis<br/>Cache + Queue)]
    end

    subgraph "AI Services"
        OLLAMA[Ollama<br/>Embeddings]
        RERANK[Reranker<br/>CrossEncoder]
    end

    subgraph "Observabilité"
        PROM[Prometheus]
    end

    UI --> INGEST
    CLI --> INGEST
    
    INGEST -->|Async| WORKER
    INGEST -->|Cache| REDIS
    INGEST --> OLLAMA
    
    WORKER --> PG
    WORKER --> OLLAMA
    WORKER --> RERANK
    
    INGEST --> PROM
    WORKER --> PROM

    style PG fill:#336791,color:#fff
    style REDIS fill:#DC382D,color:#fff
    style INGEST fill:#2196F3,color:#fff
    style WORKER fill:#FF9800,color:#fff
```

---

## Déploiement production

```mermaid
graph TB
    subgraph "Internet"
        USERS[Utilisateurs]
    end

    subgraph "VPS Host"
        subgraph "Nginx (Host)"
            NGINX_UI[Nginx UI vhost]
            NGINX_API[Nginx API vhost]
            CERTBOT[Certbot TLS]
        end

        subgraph "Docker Compose"
            subgraph "Network: rag_net"
                INGEST[Ingestor:8001]
                UI[Streamlit:8501]
                CHROMA[ChromaDB:8000]
                OLLAMA[Ollama:11434]
                PROM[Prometheus:9090]
            end

            VOLUMES[(Volumes<br/>chroma_data<br/>ollama_data<br/>uploads)]
        end
    end

    USERS -->|HTTPS:443| NGINX_UI
    USERS -->|HTTPS:443| NGINX_API
    
    NGINX_UI -->|127.0.0.1:18501| UI
    NGINX_API -->|127.0.0.1:8001| INGEST
    
    INGEST --> CHROMA
    INGEST --> OLLAMA
    INGEST --> VOLUMES
    
    UI --> CHROMA
    
    CERTBOT -.-> NGINX_UI
    CERTBOT -.-> NGINX_API

    style NGINX_UI fill:#4CAF50,color:#fff
    style NGINX_API fill:#4CAF50,color:#fff
    style INGEST fill:#2196F3,color:#fff
    style UI fill:#FF9800,color:#fff
    style CHROMA fill:#FFC107,color:#000
    style OLLAMA fill:#9C27B0,color:#fff
```

---

## Sécurité — Couches de défense

```mermaid
graph LR
    subgraph "Couche 1 — Réseau"
        FIREWALL[Firewall VPS]
        NGINX[Nginx Rate Limiting]
    end

    subgraph "Couche 2 — Transport"
        TLS[TLS 1.3]
        HSTS[HSTS]
    end

    subgraph "Couche 3 — Authentification"
        TOKEN[Token Auth]
        IPALLOW[IP Allowlist]
    end

    subgraph "Couche 4 — Application"
        SSRF[SSRF Protection]
        MIME[MIME Whitelist]
        SIZE[Size Limits]
    end

    subgraph "Couche 5 — Audit"
        LOGS[Audit Logs]
        METRICS[Prometheus]
    end

    FIREWALL --> NGINX
    NGINX --> TLS
    TLS --> TOKEN
    TOKEN --> SSRF
    SSRF --> LOGS

    style FIREWALL fill:#F44336,color:#fff
    style NGINX fill:#FF9800,color:#000
    style TLS fill:#FFC107,color:#000
    style TOKEN fill:#4CAF50,color:#fff
    style SSRF fill:#2196F3,color:#fff
    style LOGS fill:#9C27B0,color:#fff
```

---

## Data Model — pgvector (v2)

```mermaid
erDiagram
    RAG_DOCUMENTS ||--o{ RAG_CHUNKS : contains
    RAG_DOCUMENTS ||--o{ RAG_INGESTIONS : has
    
    RAG_DOCUMENTS {
        UUID id PK
        VARCHAR tenant
        VARCHAR source_type
        TEXT source_path
        TEXT title
        VARCHAR file_hash
        VARCHAR embed_model
        INTEGER embed_dim
        JSONB metadata
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }
    
    RAG_CHUNKS {
        UUID id PK
        UUID document_id FK
        VARCHAR tenant
        INTEGER chunk_index
        TEXT text
        VECTOR embedding
        INTEGER char_start
        INTEGER char_end
        JSONB metadata
    }
    
    RAG_INGESTIONS {
        UUID id PK
        UUID document_id FK
        VARCHAR status
        TEXT error_message
        INTEGER chunks_count
        TIMESTAMPTZ created_at
        TIMESTAMPTZ completed_at
    }
```

---

## Références

- [docs/adr/](./adr/) — Architecture Decision Records
- [SPEC.md](../../SPEC.md) — Spécifications API
- [docs/dossier-technique-exhaustif.md](./dossier-technique-exhaustif.md) — Dossier technique
