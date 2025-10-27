SHELL := /bin/bash

BASE := infra/docker-compose.yml
DEV  := infra/docker-compose.dev.yml
ENVF := infra/.env

compose := docker compose -f $(BASE)
ifneq ("$(wildcard $(DEV))","")
  compose := docker compose -f $(BASE) -f $(DEV)
endif

.PHONY: help
help:
	@echo "Targets: compose-up, compose-down, rebuild, logs, lint, typecheck, pylint, test, smoke"

.PHONY: compose-up up
compose-up up:
	$(compose) --env-file $(ENVF) up -d --remove-orphans

.PHONY: compose-down down
compose-down down:
	$(compose) --env-file $(ENVF) down --remove-orphans || true

.PHONY: rebuild
rebuild:
	$(compose) --env-file $(ENVF) build --pull

.PHONY: logs
logs:
	$(compose) --env-file $(ENVF) logs -n 200 --no-color

.PHONY: lint
lint:
	python -m ruff check .

.PHONY: typecheck
typecheck:
	python -m mypy src

.PHONY: pylint
pylint:
	python -m pylint src || true

.PHONY: test
test:
	pytest -q

.PHONY: smoke
smoke:
	bash scripts/smoke.sh

.PHONY: nginx-render nginx-up nginx-reload nginx-down nginx-smoke

nginx-render:
	@mkdir -p infra/nginx/rendered
	@bash -lc 'set -a; source $(ENVF); set +a; envsubst < infra/nginx/rag-ui.conf.template  > infra/nginx/rendered/rag-ui.conf'
	@bash -lc 'set -a; source $(ENVF); set +a; envsubst < infra/nginx/rag-n8n.conf.template > infra/nginx/rendered/rag-n8n.conf'
	@grep -E "server_name|client_max_body_size|proxy_pass" -n infra/nginx/rendered/*.conf || true

nginx-up: nginx-render
	$(compose) --env-file $(ENVF) up -d web

nginx-reload:
	$(compose) --env-file $(ENVF) exec -T web nginx -t
	$(compose) --env-file $(ENVF) exec -T web nginx -s reload || $(compose) --env-file $(ENVF) restart web

nginx-down:
	$(compose) --env-file $(ENVF) rm -sf web

nginx-smoke:
	@echo "== docker-network upstreams =="
	docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -fsS "http://$$(grep -E '^NGINX_UI_UPSTREAM=' $(ENVF) | cut -d= -f2)/"  -o /dev/null && echo "ui(upstream): OK" || echo "ui(upstream): KO"
	docker run --rm --network infra_rag_net curlimages/curl:8.9.1 -fsS "http://$$(grep -E '^NGINX_N8N_UPSTREAM=' $(ENVF) | cut -d= -f2)/" -o /dev/null && echo "n8n(upstream): OK" || echo "n8n(upstream): KO"
	@echo "== host via Nginx (dev ports) =="
	@host="$$((grep -E '^N8N_EXTERNAL_DOMAIN=' $(ENVF) || echo N8N_EXTERNAL_DOMAIN=localhost) | cut -d= -f2)"; \
	 curl -fsSI -H "Host: $$host" http://127.0.0.1:18080/ | head -n1 && echo "web(localhost): OK" || echo "web(localhost): KO"
