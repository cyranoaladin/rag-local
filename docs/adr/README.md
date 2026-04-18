# Architecture Decision Records (ADR)

Ce répertoire contient les Architecture Decision Records (ADR) du projet rag-local.

## Qu'est-ce qu'un ADR ?

Un ADR est un document qui capture une décision d'architecture importante, son contexte, et ses conséquences. Il suit généralement le format suivant :

1. **Titre** - Nom de la décision
2. **Statut** - Proposed, Accepted, Deprecated, Superseded
3. **Contexte** - Situation et forces en jeu
4. **Décision** - Ce qui a été décidé
5. **Conséquences** - Résultats positifs et négatifs
6. **Références** - Liens vers d'autres documents

## ADRs

| Numéro | Titre | Statut | Date |
|--------|-------|--------|------|
| [0001](adr-0001.md) | Migration de ChromaDB vers pgvector | Accepted | 2026-02-22 |
| [0002](adr-0002.md) | Architecture asynchrone avec Celery | Accepted | 2026-02-22 |
| [0003](adr-0003.md) | Hybrid Search avec RRF et Reranking | Accepted | 2026-02-22 |
| [0004](adr-0004.md) | Authentification et Sécurité API | Accepted | 2026-03-01 |
| [0005](adr-0005.md) | Audit Logging pour les opérations admin | Accepted | 2026-03-01 |

## Format des ADRs

Les ADRs sont écrits en Markdown et suivent la convention de nommage `adr-NNNN.md` où NNNN est un numéro séquentiel à 4 chiffres.

## Références

- [GitHub ADR Template](https://github.com/joelparkerhenderson/architecture-decision-record)
- [ThoughtWorks ADR Format](https://thoughtworks.com/radar/techniques/architecture-decision-records)
