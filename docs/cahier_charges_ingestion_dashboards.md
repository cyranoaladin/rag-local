# Cahier des charges – Dashboards d’ingestion & API RAG externe

Statut: V1 implémentée (Admin CRUD complet, endpoint global /admin/ingestions, upload via dashboard, ingestion URL & Google Drive opérationnelles).

## 1. Contexte

`rag-local` est un moteur RAG 100 % local (FastAPI + Ollama + ChromaDB + Streamlit) déployé sur VPS, sans dépendance à des LLM externes.  
L’ingestion actuelle se fait via l’endpoint `POST /ingest` (SPEC.md), déclenché par des outils externes (n8n, scripts, etc.), et la recherche se fait via l’UI Streamlit existante.

L’objectif de cette extension est de fournir :
1. Des **dashboards d’ingestion métier** pour deux domaines fonctionnels :
   - **Domaine "Lycée"** : corpus pédagogique et institutionnel (maths, NSI, documents d’établissement).
   - **Domaine "Web3 / Blockchain / Solana"** : corpus technique pour la blockchain, le Web3 et l’écosystème Solana.
2. Une **API de consultation RAG** générique, permettant à des agents externes (autres services / backends / agents IA) de :
   - requêter la base RAG,
   - filtrer par domaine et métadonnées,
   - récupérer des passages et métadonnées pour construire leurs propres réponses.

## 2. Objectifs

### 2.1. Dashboards d’ingestion

Fournir une interface d’administration simple (dans le scope de `rag-local`) permettant :

- De **déclarer des documents logiques** (fiches document) avec métadonnées :
  - Domaine : `lycee` ou `web3`.
  - Type de ressource (cours, TD, docs officiels, whitepaper, etc.).
  - Informations spécifiques par domaine (niveau / discipline pour le lycée, thèmes Web3/Solana, etc.).
  - Source : fichier local, URL, élément GDrive, etc.

- De **lancer, relancer et suivre** des jobs d’ingestion :
  - L’UI ne fait que **piloter l’endpoint existant** `POST /ingest` et enregistrer les runs (succès/erreurs, timestamps).
  - Chaque ingestion enrichit les métadonnées envoyées à Chroma avec :
    - `domain` = `lycee` ou `web3`,
    - `document_id` (UUID logique du document),
    - autres métadonnées utiles pour le filtrage.

- D’offrir, pour chaque document ou ensemble de documents, un **petit outil de test RAG** :
  - champ de question,
  - affichage des passages top-k et de la réponse,
  - filtrage automatique sur `domain` et éventuellement `document_id`.

### 2.2. API RAG pour agents externes

Mettre à disposition une **API stable** permettant à des services externes d’exploiter le RAG :

- Endpoint de **recherche** (par ex. `POST /rag/query`) prenant en entrée :
  - `query` (texte),
  - paramètres de filtrage (`domain`, `document_id`, `tags`, etc.),
  - éventuellement `top_k`.

- Réponse structurée contenant :
  - les passages retrouvés (texte),
  - les métadonnées associées (dont `domain`, `document_id`, type, niveau / thème…),
  - les scores de similarité.

Contraintes :
- L’API doit rester **compatible avec la philosophie "local-first"**.
- L’accès doit être **authentifié** (par exemple via le même mécanisme de token que `/ingest` + protections Nginx).

## 3. Périmètre

### Inclus

- Modélisation d’un **catalogue de documents** et de **jobs d’ingestion** :
  - stockage persistant (SQLite ou équivalent),
  - lien explicite entre un document logique et les chunks Chroma via `document_id` et `domain`.

- UI d’administration (Streamlit ou module dédié) avec :
  - liste des documents,
  - formulaire de création/édition,
  - déclenchement d’ingestions,
  - vue historique / statut des ingestions,
  - test RAG rapide avec filtres par domaine.

- API RAG externe :
  - au minimum un endpoint de recherche textuelle filtrable,
  - documentation minimale (payloads exemples).

### Hors périmètre (v1)

- Gestion fine des utilisateurs / rôles (un **profil admin unique** suffit).
- Intégration spécifique à un projet particulier (par ex. simulateurs externes) : les consommateurs externes utiliseront simplement l’API RAG générique.
- Ingestion automatique de gros corpus Web (scraping massif) : seule la **capacité à déclarer/ingérer** les sources fournies est nécessaire.

## 4. Exigences techniques

- **Ne pas casser l’API `/ingest` existante** :
  - les dashboards utilisent `/ingest` comme client interne.
  - les métadonnées supplémentaires sont passées dans les champs prévus à cet effet.

- **Enrichir les métadonnées Chroma** :
  - chaque chunk doit contenir `domain`, `document_id` et quelques champs clés (type, niveau / thème).

- **Sécurité** :
  - réutiliser les mécanismes d’authentification existants (token, Nginx, TLS),
  - restreindre l’accès à l’interface d’administration.

- **Tests** :
  - tests unitaires pour le catalogue (documents, ingestion runs),
  - tests d’intégration pour un scénario d’ingestion par domaine,
  - tests de l’API `/rag/query`.

## 5. Résultat attendu

À l’issue du développement :

- Un **catalogue** de documents et jobs d’ingestion dans `rag-local`.
- Deux **dashboards d’ingestion** utilisables en production :
  - un pour le corpus Lycée,
  - un pour le corpus Web3 / Blockchain / Solana.
- Une **API RAG** stable, authentifiée, et documentée, accessible pour toute intégration future (agents IA, simulateurs, backends externes, etc.).
```

---

### 2. Schémas ASCII / pseudo-UML des flux d’ingestion par domaine

#### 2.1. Vue architecture globale (par domaine)

```text
                           +------------------+
                           |    Admin UI      |
                           | (Streamlit etc.) |
                           +--------+---------+
                                    |
                         (HTTP / admin endpoints)
                                    |
                                    v
+---------------------+    +---------------------+    +-------------------+
| Admin / Catalog API |    |    Ingestor API    |    |    RAG Query API  |
|  /admin/documents   |    |   POST /ingest     |    |  POST /rag/query  |
+----------+----------+    +----------+---------+    +----------+--------+
           |                          |                       |
           | CRUD docs / runs         | déclenche ingestion   | requêtes externes
           v                          v                       v
    +-------------+         +------------------+       +--------------+
    |  SQLite /   |         |  Ollama (embed)  |       |   ChromaDB   |
    |  Catalogue  |         +------------------+       | (vectors +   |
    | (docs,runs) |                 |                  |  metadata)   |
    +-------------+                 |                  +--------------+
                                    | write embeddings
                                    v
                              +-------------+
                              |  ChromaDB   |
                              | collection  |
                              | (chunks)    |
                              +-------------+
                             domain = lycee / web3
                             document_id = UUID
```

#### 2.2. Flux d’ingestion Domaine **Lycée** (séquence)

```text
Acteurs: AdminLycée, Admin UI, Admin API, Ingestor API, Ollama, ChromaDB, Catalogue

AdminLycée -> Admin UI        : Crée/édite "fiche document" (Chapitre Suites Terminale, type=COURS, domaine=lycee, source=fichier PDF)
Admin UI   -> Admin API       : POST /admin/documents  { domain: "lycee", ... }
Admin API  -> Catalogue       : INSERT document (id = DOC_L1)

AdminLycée -> Admin UI        : Clique "Lancer ingestion"
Admin UI   -> Admin API       : POST /admin/ingest { document_id: "DOC_L1" }
Admin API  -> Catalogue       : INSERT ingestion_run (status="in_progress")
Admin API  -> Ingestor API    : POST /ingest { source: ..., metadata: { domain:"lycee", document_id:"DOC_L1", ... } }

Ingestor API -> Ollama        : génère embeddings
Ollama       -> ChromaDB      : upsert chunks avec metadata (domain="lycee", document_id="DOC_L1", ...)

Ingestor API -> Admin API     : OK / erreur
Admin API    -> Catalogue     : UPDATE ingestion_run (status, timestamps, chunks_count)
Admin API    -> Admin UI      : statut mis à jour
```

#### 2.3. Flux d’ingestion Domaine **Web3 / Blockchain / Solana** (séquence)

```text
Acteurs: AdminWeb3, Admin UI, Admin API, Ingestor API, Ollama, ChromaDB, Catalogue

AdminWeb3 -> Admin UI         : Crée/édite "fiche document" (Solana Core docs, thème=Solana_Core, type=Doc_officielle, domaine=web3)
Admin UI  -> Admin API        : POST /admin/documents { domain:"web3", theme:"Solana_Core", source: URL ou chemin local, ... }
Admin API -> Catalogue        : INSERT document (id = DOC_W1)

AdminWeb3 -> Admin UI         : Clique "Lancer ingestion"
Admin UI  -> Admin API        : POST /admin/ingest { document_id: "DOC_W1" }
Admin API -> Catalogue        : INSERT ingestion_run (status="in_progress")
Admin API -> Ingestor API     : POST /ingest { source: ..., metadata: { domain:"web3", document_id:"DOC_W1", theme_principal:"Solana_Core", ... } }

Ingestor API -> Ollama        : génère embeddings
Ollama       -> ChromaDB      : upsert chunks (domain="web3", document_id="DOC_W1", theme_principal="Solana_Core", ...)

Ingestor API -> Admin API     : OK / erreur
Admin API    -> Catalogue     : UPDATE ingestion_run
Admin API    -> Admin UI      : affiche le statut

(Plus tard)
ExternalAgent -> RAG Query API: POST /rag/query { query: "...", filters: { domain:"web3", theme_principal:"Solana_Core" } }
RAG Query API -> ChromaDB     : similarity search + filter
ChromaDB      -> RAG Query API: chunks + metadata
RAG Query API -> ExternalAgent: résultats structurés
```

---

### 3. Plan de découpage en tâches GitHub Issues

Voici une proposition de plan structuré en “épiques” + issues.
Chaque point peut devenir une issue (ou une checklist dans une issue parent).

#### ÉPIQUE 1 – Modèle de catalogue & stockage

1. **Définir le modèle de données "Document logique"**

   * Décrire les champs : `id`, `domain`, `title`, `source_type`, `source_location`, `tags`, `metadata`, `created_at`, `updated_at`, `last_ingest_at`, `last_ingest_status`.
   * Distinguer les deux domaines via `domain = "lycee" | "web3"`.
   * Ajouter la structure `metadata` pour :

     * Lycée : niveau, discipline, type_ressource, année_scolaire…
     * Web3 : theme_principal, sous_theme, type_ressource, origine, niveau_cible…

2. **Implémenter le stockage (SQLite ou équivalent)**

   * Créer la base `catalog.sqlite` (ou autre solution simple mais persistante).
   * Créer les tables :

     * `documents` (modèle ci-dessus),
     * `ingestion_runs` (`id`, `document_id`, `started_at`, `finished_at`, `status`, `error_message`, `chunks_count`).
   * Fournir fonctions CRUD internes (create/read/update/delete) pour ces deux entités.

3. **Lister les documents depuis le backend**

   * Endpoint interne (ou fonctions) pour :

     * récupérer la liste des documents avec filtres simples (par domain, type, etc.),
     * récupérer l’historique des ingestion_runs d’un document.

---

#### ÉPIQUE 2 – API Admin (option recommandée : FastAPI)

4. **Créer module API Admin pour le catalogue**

   * Nouveaux endpoints :

     * `GET /admin/documents` (liste, filtres de base),
     * `POST /admin/documents` (création),
     * `PUT /admin/documents/{id}` (mise à jour),
     * `GET /admin/documents/{id}` (détail),
     * `GET /admin/documents/{id}/ingestions` (historique des runs).

5. **Créer endpoint d’ingestion pilotée par document**

   * Endpoint `POST /admin/ingest` ou `POST /admin/documents/{id}/ingest` :

     * lit la fiche document (source, metadata, domain),
     * enregistre un ingestion_run (status = "in_progress"),
     * appelle `POST /ingest` avec les paramètres et métadonnées nécessaires (`domain`, `document_id`, etc.),
     * met à jour ingestion_run à la fin (status, erreurs, chunks_count).

6. **Sécuriser les endpoints `/admin/*`**

   * Réutiliser le token d’authentification existant ou un second token dédié admin.
   * S’assurer que ces endpoints sont non accessibles publiquement (Nginx / BasicAuth).

---

#### ÉPIQUE 3 – Enrichissement des métadonnées pour Chroma

7. **Adapter l’appel à `/ingest` côté admin**

   * Lorsqu’un document est ingéré via `/admin/ingest`, injecter systématiquement dans le payload :

     * `metadata.domain`,
     * `metadata.document_id`,
     * les métadonnées spécifiques au domaine (niveau / discipline ou theme_principal / niveau_cible, etc.).

8. **S’assurer que Chroma indexe bien ces métadonnées**

   * Vérifier que les chunks enregistrés dans Chroma contiennent les champs attendus.
   * Mettre en place une fonction de diagnostic simple (ex : un endpoint interne ou une fonction CLI pour inspecter un document donné).

---

#### ÉPIQUE 4 – UI Dashboards d’ingestion (Streamlit)

9. **Dashboard – Vue liste des documents**

   * Dans l’UI Streamlit :

     * ajouter des onglets / pages :

       * “Lycée” (filtre `domain=lycee`),
       * “Web3 / Blockchain / Solana” (filtre `domain=web3`).
     * afficher la liste des documents :

       * colonnes : titre, type, domain, dernière ingestion, statut.
       * filtres : niveau / discipline (Lycée), theme_principal (Web3), statut d’ingestion.

10. **Dashboard – Formulaire de création / édition**

    * Formulaire Streamlit permettant :

      * de créer une fiche document (choix du domaine, type, source, métadonnées spécifiques),
      * de mettre à jour une fiche existante.
    * Appeler l’API Admin (`POST /admin/documents`, `PUT /admin/documents/{id}`).

11. **Dashboard – Déclenchement d’ingestion & suivi**

    * Bouton “Ingestion” sur chaque ligne de document :

      * appelle `POST /admin/documents/{id}/ingest`,
      * affiche un retour visuel (spinner, statut),
      * rafraîchit la liste / l’historique des ingestion_runs.
    * Mini vue “Historique” pour un document (liste des derniers runs, statut, date).

12. **Dashboard – Zone de test RAG filtrée**

    * Dans la fiche document ou dans un onglet “Test” :

      * champ de texte pour la question,
      * sélection d’un filtre (document courant / domaine complet),
      * appel de l’API RAG (cf. ÉPIQUE 5),
      * affichage des passages retournés et métadonnées.

---

#### ÉPIQUE 5 – API RAG générique pour agents externes

13. **Définir et implémenter l’endpoint /rag/query**

    * Endpoint `POST /rag/query` :

      * Body attendu (exemple) :

        ```json
        {
          "query": "texte de la question",
          "filters": {
            "domain": "lycee",
            "document_id": "…",
            "tags": ["…"],
            "metadata": {
              "niveau": "Terminale",
              "theme_principal": "Solana_Core"
            }
          },
          "top_k": 5
        }
        ```
      * Comportement :

        * effectue une recherche dans Chroma (similarité),
        * applique les filtres métadonnées,
        * renvoie les passages + métadonnées + score.

14. **Structurer la réponse**

    * Réponse JSON type :

      ```json
      {
        "results": [
          {
            "text": "…",
            "score": 0.87,
            "metadata": {
              "domain": "lycee",
              "document_id": "…",
              "title": "Chapitre Suites",
              "niveau": "Terminale",
              "discipline": "Mathématiques"
            }
          }
        ]
      }
      ```
    * Documenter les champs.

15. **Sécuriser /rag/query**

    * Authentification (token).
    * Option : limiter `/rag/query` à certaines IP / via Nginx.

16. **Documenter l’API RAG**

    * Fichier `docs/api_rag_query.md` décrivant :

      * payloads d’exemple,
      * champs disponibles dans `filters`,
      * exemples d’usage pour domaine Lycée et Web3.

---

#### ÉPIQUE 6 – Observabilité, tests, documentation

17. **Métriques d’ingestion par domaine**

    * Ajouter (ou enrichir) des métriques Prometheus existantes avec un label `domain`.
    * Exemple : `ingestor_ingests_total{domain="lycee"}`, `ingestor_ingest_failures_total{domain="web3"}`.

18. **Tests unitaires et d’intégration**

    * Tests pour :

      * CRUD catalogue,
      * endpoint admin d’ingestion,
      * endpoint `/rag/query` (avec un mini jeu de données).
    * Scénarios end-to-end simples :

      * ingestion d’un document Lycée puis requête RAG filtrée,
      * ingestion d’un document Web3 puis requête RAG filtrée.

19. **Documentation utilisateur**

    * Mettre à jour le `README.md` principal pour mentionner :

      * l’existence des dashboards d’ingestion,
      * l’API RAG pour agents externes.
    * Ajouter (ou compléter) :

      * `docs/cahier_charges_ingestion_dashboards.md` (version courte ci-dessus),
      * `docs/api_rag_query.md`,
      * éventuellement `docs/admin_guide.md` pour l’utilisation pratique des dashboards.

---

Avec ces trois éléments (cahier des charges court, schémas, plan d’issues), on a un cadre clair :

* ce qu’il doit construire dans `rag-local`,
* comment les domaines "Lycée" et "Web3" sont modélisés,
* quelle API RAG générique devra être exposée pour que, plus tard, d’autres projets (simulateurs, agents IA) puissent se brancher sans modification supplémentaire du cœur RAG.

