# Tableau de bord RAG unifié — feuille de route

## Objectifs
- Centraliser toutes les instances RAG vers `rag-local` (FastAPI + Chroma + n8n + UI).
- Offrir un tableau de bord sécurisé sur `rag.nexusreussite.academy` pour gérer contenus, dossiers, ingestions et statistiques.
- Proposer une authentification applicative (utilisateurs / rôles) pour remplacer le Basic Auth Nginx.
- Étendre l'API pour la gestion des dossiers, des documents et des historiques d'ingestion.
- Garantir la compatibilité avec les flux existants (UI Streamlit, automatisations n8n, autres domaines).

## Architecture cible
- **Backend principal (FastAPI)**
  - Module `core` : gestion des utilisateurs, authentification JWT, rôles, sessions.
  - Module `folders` : CRUD dossiers, association aux contenus Chroma.
  - Module `ingestions` : orchestration ingestion multi-format, suivi des statuts, journalisation.
  - Module `stats` : métriques agrégées (volumes, répartition par format, tendances).
  - Base relationnelle PostgreSQL (service Docker) pour persister utilisateurs, dossiers, logs.
- **Service RAG existant** : ingestion dans Chroma inchangée mais orchestrée par le backend.
- **UI Dashboard** (`dashboard-ui`)
  - Frontend (Next.js ou Streamlit custom) avec pages : connexion, overview, ingestion, dossiers, historique, administration.
  - Consomme les APIs du backend via JWT, gère uploads sécurisés.
- **n8n** : workflows mis à jour pour interagir avec les nouveaux endpoints.
- **Nginx** : vhost `rag.nexusreussite.academy` pointant vers `dashboard-ui`; headers de sécurité renforcés.

## Étapes principales
1. **Fondations backend**
   - Ajouter Postgres dans `docker-compose.yml` + migrations Alembic.
   - Créer `src/backend` (FastAPI) avec endpoints `/health`, `/auth/login`, `/auth/register`, `/users/me`.
   - Implémenter couche ORM (SQLAlchemy 2.x) et dépendances (hashage bcrypt, JWT via `python-jose`).
   - Couvrir par tests (`tests/backend`).

2. **Gestion dossiers & documents**
   - Modèles `Folder`, `Document`, `IngestionLog`.
   - Endpoints CRUD (list, create, update, delete) avec permissions.
   - API pour lier ingestion existante à un dossier (pipeline orchestré côté backend puis appel API Ingestor).
   - Scripts de migration pour associer les contenus Chroma existants (via métadonnées `metadata.hints`).

3. **Dashboard UI**
   - Décider framework : Next.js (service Node) ou Streamlit enrichi.
   - Implémenter écrans : connexion, overview (stats), ingestion (drag & drop + URL), dossiers (arborescence), historique.
   - Intégrer authentification (JWT stocké en cookie HTTPOnly), appels API typés.
   - Tests E2E (Playwright/Cypress) + linting.

4. **Intégration & sécurité**
   - Mettre à jour Nginx (`rag.nexusreussite.academy`) pour le nouveau service; conserver `rag-ui`, `rag-n8n` existants.
   - Retirer Basic Auth au profit de l’auth applicative, prévoir redirections 301.
   - Configurer rate limiting uploads, renforcer CSP.

5. **Migration & synchronisation**
   - Script de migration (`scripts/migrate_rag_data.py`) pour transférer dossiers existants (tags) vers nouvelles tables.
   - Import automatique des workflows n8n (via API) et mise à jour des URL cible.
   - Backups & rollback plan documentés (`docs/ops/migration-guide.md`).

6. **Communication inter-domaines**
   - Documenter API publique (`docs/api/dashboard-openapi.md`).
   - Fournir tokens/service accounts pour autres domaines.
   - Mettre à jour clients existants (scripts, n8n, UI) pour pointer vers le backend unique.

## Livrables
- Code backend (`src/backend`) + tests.
- Nouveau service dashboard (`dashboard-ui` + Dockerfile, pipeline npm).
- Configurations Compose & Nginx mises à jour.
- Scripts de migration et de backup.
- Documentation utilisateur et opérateur.

## Risques & atténuation
- **Migration données** : tester sur snapshot, prévoir rollback des volumes.
- **Charge serveur** : surveiller CPU/RAM, dimensionner Postgres et n8n.
- **Sécurité** : audits JWT, validations, limiter uploads, journaliser.
- **Maintenance** : automatiser tests (CI) et smoke tests post déploiement.

## Étapes suivantes
- Mettre à jour les dépendances (SQLAlchemy, passlib, python-jose).
- Générer squelette backend + tests basiques.
- Ajouter Postgres au `docker-compose.yml` et script provisioning.
- Définir modèle de données (diagramme ER) et écrire migrations initiales.

Ce document vit avec le projet ; ajustez-le au fil des développements.
