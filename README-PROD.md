# rag-local — Runbook Production (VPS)

Ce runbook décrit **l’installation, l’exploitation et la maintenance** de rag-local en production, 100% **sans clés API externes** (LLM & embeddings via **Ollama**).

## 0. Architecture (rappel)
- **Ollama** (`ollama`) : sert les modèles locaux (ex. `llama3.2:latest`, `nomic-embed-text`).
- **ChromaDB** (`chroma`) : base vectorielle (API **v2**).
- **Ingestor** (`ingestor`) : FastAPI qui ingère fichiers/URL/Google Drive → Chroma.
- **UI** (`ui`) : Streamlit (recherche RAG).
- **n8n** (`n8n`) : orchestrations (ingestions planifiées, pipelines GDrive, etc.).
- **Nginx + TLS** (hors compose) : reverse-proxy public (UI et n8n).

## 1. Prérequis VPS
- Ubuntu 22.04/24.04, utilisateur sudo.
- Ports **80/443** ouverts, DNS pointant vers le VPS.
- Docker + Compose plugin :
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## 2. Récupération du projet

```bash
git clone https://github.com/cyranoaladin/rag-local
cd rag-local
```

## 3. Paramétrage

Copiez l’exemple et adaptez **infra/.env** :

```bash
cp infra/.env.example infra/.env
```

Champs importants :

* `TZ` (ex. `Africa/Tunis`)
* `NGINX_N8N_PORT` (ex. `15678`), `NGINX_UI_PORT` (ex. `18501`)
* Modèles : `EMBED_MODEL=nomic-embed-text`, `SMALL_LLM=llama3.2:latest`
* n8n Basic Auth : `N8N_BASIC_AUTH_*` (recommandé en prod)

Créer un placeholder pour les creds (GDrive service account facultatif au départ) :

```bash
mkdir -p infra/creds
printf '{}' > infra/creds/gdrive-service-account.json
```

## 4. Démarrage des services

Validation :

```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env config
```

Démarrage progressif :

```bash
# Base + LLM
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d chroma ollama

# Pré-télécharger les modèles (1ère fois)
docker compose -f infra/docker-compose.yml exec -T ollama sh -lc '
  set -e
  ollama pull nomic-embed-text:latest
  ollama pull "llama3.2:latest"
  ollama list
'

# API d’ingestion + UI
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d ingestor ui

# (optionnel) n8n
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d n8n
```

Quick checks (réseau interne) :

```bash
docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -sSI http://chroma:8000/api/v2/heartbeat | head -n1
docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -sS  http://ollama:11434/api/version && echo
docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -sSI http://ingestor:8001/health | head -n1
docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -sSI http://ui:8501/ | head -n1
```

Accès local (loopback) :

* UI : [http://127.0.0.1:`$NGINX_UI_PORT`](http://127.0.0.1:`$NGINX_UI_PORT`)
* n8n : [http://127.0.0.1:`$NGINX_N8N_PORT`](http://127.0.0.1:`$NGINX_N8N_PORT`) (si démarré)

## 5. Publication publique (Nginx + TLS)

Exemple **server block** pour UI :

```
server {
  listen 80;
  server_name rag-ui.example.com;
  return 301 https://$host$request_uri;
}
server {
  listen 443 ssl http2;
  server_name rag-ui.example.com;

  # Certificats (Let's Encrypt)
  ssl_certificate     /etc/letsencrypt/live/rag-ui.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/rag-ui.example.com/privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:18501/;
    include proxy_params;
    proxy_read_timeout 3600s;
  }
}
```

Même principe pour n8n (port 15678). Obtenez les certificats via `certbot --nginx`.

## 6. Ingestion — Exemples rapides

* **URL** :

```bash
curl -sS -X POST http://127.0.0.1:8001/ingest \
 -H 'Content-Type: application/json' \
 -d '{"source":"https://www.example.com/","source_type":"url",
      "hints":{"matiere":"NSI","niveau":"terminale"}}'
```

* **Fichier local** (montez un volume ou utilisez un upload endpoint si activé).
* **Google Drive** : placez le JSON service account dans `infra/creds/` puis suivez la doc `SPEC.md` (section GDrive).

## 7. Sauvegardes & restauration

Sauvegarde des volumes (ex. Chroma) :

```bash
mkdir -p backups
docker run --rm -v infra_rag_chroma_data:/data -v $PWD/backups:/backups alpine \
  sh -lc 'tar czf /backups/chroma-$(date +%Y%m%d-%H%M%S).tgz -C / data'
```

Restauration :

```bash
docker run --rm -v infra_rag_chroma_data:/data -v $PWD/backups:/backups alpine \
  sh -lc 'rm -rf /data/* && tar xzf /backups/<chroma-TS>.tgz -C /'
```

Répétez pour `infra_rag_n8n_data` si n8n est en prod.

## 8. Opérations courantes

```bash
# État
docker compose -f infra/docker-compose.yml ps
# Logs
docker compose -f infra/docker-compose.yml logs -f ingestor ui chroma ollama n8n
# Recréer un service
docker compose -f infra/docker-compose.yml up -d --force-recreate ingestor
# Mise à jour images
docker compose -f infra/docker-compose.yml pull && docker compose -f infra/docker-compose.yml up -d
```

## 9. Dépannage

* **Chroma v2** : utilisez `/api/v2/tenants/default_tenant/databases/default_database/collections`.
* **Ollama “no compatible GPUs”** : normal en CPU-only (runners `cpu_avx2`).
* **Healthchecks** : l’API Ingestor répond `/health` **200** quelques secondes après le start.
* **GDrive** : vérifiez le JSON service account, scopes Drive, et droits sur les dossiers/fichiers.

## 10. Sécurité minimale

* Activez `N8N_BASIC_AUTH_*`.
* Maintenez Docker/OS à jour.
* Restreignez l’accès SSH (clé, fail2ban, ufw).
* Ne publiez pas Chroma/Ollama en clair — seulement via l’Ingestor et l’UI.
