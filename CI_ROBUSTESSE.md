# CI/CD Robustesse & Auto-diagnostic

## Diagnostic automatique en cas d'échec

Le script `infra/scripts/smoke.sh` a été renforcé pour :
- Afficher l'état des conteneurs (`docker ps -a`),
- Inspecter le conteneur ingestor (`docker inspect`),
- Afficher les ports ouverts (`netstat` ou `ss`),
- Dumper tous les logs de tous les services Compose,
- Et ce, automatiquement en cas d'échec du health check ou d'un service non healthy.

## Boucle de health check
- Le script attend jusqu'à 60 tentatives (2 minutes) pour que tous les services soient healthy.
- En cas d'échec, tous les diagnostics sont affichés pour faciliter le debug CI.

## Bonnes pratiques
- Toujours consulter la sortie complète du job CI en cas d'échec : tous les logs et états sont automatiquement affichés.
- Pour reproduire localement :
  ```bash
  bash infra/scripts/smoke.sh
  ```
- Pour forcer un dump manuel :
  ```bash
  bash infra/scripts/smoke.sh || true
  ```

## Pour aller plus loin
- Voir `infra/scripts/smoke.sh` pour la logique complète.
- Voir `.github/workflows/ci-smoke-compose.yml` pour l'intégration CI.
- Pour toute anomalie persistante, vérifier les diagnostics réseau et logs générés automatiquement.
