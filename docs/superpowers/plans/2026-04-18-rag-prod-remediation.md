# RAG Prod Remediation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce false-positive RAG results by blocking binary media from text ingestion, adding a server-side search distance threshold, and exposing that threshold in the UI while keeping prod and the local repo aligned enough for repeatable fixes.

**Architecture:** The backend remains the source of truth for admissible search hits. The UI only passes optional threshold controls and renders filtered results. Prod-only operational cleanup is handled after code deployment, with explicit backups and verification against the live API.

**Tech Stack:** FastAPI, Streamlit, ChromaDB, Ollama embeddings, pytest, Docker Compose, SSH/rsync.

---

## Chunk 1: Local Regression Coverage

### Task 1: Search Threshold Tests

**Files:**
- Modify: `tests/test_ingestor_unit.py`
- Test: `tests/test_ingestor_unit.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- `/search` accepts `score_threshold`
- hits with `distance > score_threshold` are excluded
- `include_documents=false` omits `document` from the payload

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pytest tests/test_ingestor_unit.py -k "search_threshold or include_documents" -q`
Expected: FAIL because `SearchRequest` and `search_kb` do not yet implement threshold filtering.

### Task 2: Upload Guardrail Tests

**Files:**
- Modify: `tests/test_ingestor_unit.py`
- Test: `tests/test_ingestor_unit.py`

- [ ] **Step 1: Write the failing tests**

Add tests that prove:
- multipart upload rejects media files when `mode=text`
- multipart upload rejects media files when `MULTIMODAL_ENABLED=false`
- text-like uploads still pass the source-type auto-detection path

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `pytest tests/test_ingestor_unit.py -k "upload_media" -q`
Expected: FAIL because the current endpoint still routes media uploads into the multimodal/text decision too late.

## Chunk 2: Local Backend/UI Fixes

### Task 3: Backend Search Filtering

**Files:**
- Modify: `src/ingestor/api.py`
- Test: `tests/test_ingestor_unit.py`

- [ ] **Step 1: Implement the minimal backend change**

Add:
- `score_threshold: float | None` to `SearchRequest`
- post-query filtering by Chroma distance
- response `k` based on retained hits
- safe handling when `include_documents` is false

- [ ] **Step 2: Run the targeted backend tests**

Run: `pytest tests/test_ingestor_unit.py -k "search_threshold or include_documents" -q`
Expected: PASS

### Task 4: Upload Media Guardrails

**Files:**
- Modify: `src/ingestor/api.py`
- Test: `tests/test_ingestor_unit.py`

- [ ] **Step 1: Implement the minimal upload change**

Reject AV/image uploads early when:
- `mode != "multimodal"`
- or `MULTIMODAL_ENABLED=false`

Return a clear 400 message instead of allowing accidental text/markdown ingestion.

- [ ] **Step 2: Run the targeted upload tests**

Run: `pytest tests/test_ingestor_unit.py -k "upload_media" -q`
Expected: PASS

### Task 5: UI Threshold Exposure

**Files:**
- Modify: `src/ui/app.py`
- Test: `tests/test_ui_helpers.py`

- [ ] **Step 1: Add the UI control**

Expose an optional search distance threshold control and pass it to `/search` only when enabled.

- [ ] **Step 2: Add or update a focused UI helper test**

Verify the outgoing search payload contains `score_threshold` only when configured.

- [ ] **Step 3: Run the targeted UI tests**

Run: `pytest tests/test_ui_helpers.py -q`
Expected: PASS

## Chunk 3: Prod Alignment and Deployment

### Task 6: Backup and Patch Live Files

**Files:**
- Backup/Modify: `/srv/nexusreussite/rag-ui/compose/ingestor/api.py`
- Backup/Modify: `/srv/nexusreussite/rag-ui/compose/ui/app_v2.py`

- [ ] **Step 1: Snapshot prod files before changes**

Use timestamped backups or rsync copies.

- [ ] **Step 2: Port the validated local logic to prod codepaths**

Apply the same backend threshold filtering and upload media guardrails to the deployed FastAPI file, then expose the UI threshold in `app_v2.py`.

- [ ] **Step 3: Rebuild and restart only the relevant services**

Run: `docker compose build ingestor ui && docker compose up -d ingestor ui`
Expected: services restart healthy without affecting unrelated stacks.

## Chunk 4: Chroma Cleanup and Verification

### Task 7: Clean Polluted Search Data

**Files:**
- Operational only: ChromaDB HTTP API / inspection commands

- [ ] **Step 1: Export counts and sample polluted records**

Record collection counts and a sample of the targeted `.webm/.mkv/.mp4` records.

- [ ] **Step 2: Delete only polluted binary-ingested records**

Delete chunks where the source path indicates unsupported media ingestion, not all markdown blindly.

- [ ] **Step 3: Remove the temporary audit collection**

Delete `audit_tmp_8559ee70` if present.

### Task 8: Verify End-to-End

**Files:**
- Verification only

- [ ] **Step 1: Run fresh local verification**

Run: `pytest tests/test_ingestor_unit.py tests/test_ui_helpers.py -q`
Expected: PASS

- [ ] **Step 2: Run fresh prod verification**

Check:
- `curl https://rag-api.nexusreussite.academy/health`
- authenticated `/search` on a representative query
- UI search on `https://rag-ui.nexusreussite.academy/`

Expected: no media garbage in top hits, lower-noise results, services healthy.
