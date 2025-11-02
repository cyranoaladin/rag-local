# Observability

## Prometheus Endpoint
- Service: FastAPI ingestor (`src/ingestor/api.py`).
- Route: `GET /metrics` (listen-only when `METRICS_ENABLED=true`). Feature flag defaults to `false` in `infra/.env.example`.
- Metrics:
  - `ingestor_ingests_total{source,modality,status}` counter (labels include source type, modality, outcome).
  - `ingestor_ingest_duration_seconds{source,modality}` histogram with VPS-friendly buckets `[0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, +Inf]`.
- Disabled flag means the Prometheus client is not imported—no runtime overhead on constrained VPS.

## Scraping Topology
- Expose `/metrics` only on the internal network (e.g. behind Nginx with CIDR allowlist).
- Example Prometheus static scrape:
  ```yaml
  scrape_configs:
    - job_name: rag-ingestor
      metrics_path: /metrics
      scheme: http
      static_configs:
        - targets: ['127.0.0.1:8001']
      relabel_configs:
        - source_labels: [__address__]
          target_label: instance
          replacement: rag-vps
  ```
- For dockerised Prometheus, point to the ingestor container name (e.g. `ingestor:8001`).

## Alerting Snippets
1. **Ingestion Failures** — trigger when any non-success status occurs in the last 5 minutes:
   ```promql
   sum(increase(ingestor_ingests_total{status!="success"}[5m])) > 0
   ```
2. **High Latency** — watch p99 latency above 4s:
   ```promql
   histogram_quantile(0.99,
     sum(rate(ingestor_ingest_duration_seconds_bucket[5m])) by (le)
   ) > 4
   ```

Couple alerts with PagerDuty/Alertmanager routes as appropriate for VPS operations. Document any new SLOs in `AUDIT_CHECKLIST.md` when extending the stack.
