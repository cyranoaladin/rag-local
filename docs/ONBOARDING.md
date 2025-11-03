# Onboarding
- python -m venv .venv && source .venv/bin/activate
- pip install -r requirements.txt -r requirements-dev.txt
- make lint && make typecheck && make test
- docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
- make smoke
