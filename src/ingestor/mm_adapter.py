"""Utilities to parse files into multimodal chunks with Prometheus instrumentation."""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Dict, Iterator

from .metrics import record_mm_chunk, record_mm_failure, track_mm_parse_latency

LOGGER = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a multimodal chunk ready for ingestion."""

    modality: str
    text: str | None = None
    blob: bytes | None = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def approx_bytes(self) -> int:
        if self.blob is not None:
            return len(self.blob)
        if self.text is not None:
            return len(self.text.encode("utf-8"))
        return 0

    def as_text(self) -> str:
        if self.text is not None:
            return self.text
        if self.blob is not None:
            preview = base64.b64encode(self.blob[:2048]).decode("ascii")
            return f"[{self.modality} chunk base64={preview}]"
        return ""


def parse_multimodal(
    file: IO[bytes],
    filename: str,
    mime: str,
    *,
    timeout_s: float,
    max_chars_per_chunk: int,
    cache_dir: str,
) -> Iterator[Chunk]:
    """Yield multimodal chunks while emitting metrics."""

    cache_root = Path(cache_dir or os.getcwd())
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive guard
        LOGGER.debug("Unable to prepare cache directory %s: %s", cache_root, exc)

    raw_bytes = _read_all(file)
    if not raw_bytes:
        return

    base_metadata = {
        "filename": filename,
        "mime": mime,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }

    chunks: list[Chunk]
    start = time.perf_counter()
    try:
        with track_mm_parse_latency():
            if timeout_s <= 0:
                raise TimeoutError("timeout forced by configuration")
            chunks = _simple_parse(raw_bytes, mime, base_metadata, max_chars_per_chunk)
    except TimeoutError:
        LOGGER.warning("Multimodal parse timed out for %s", filename)
        record_mm_failure("timeout")
        chunks = _fallback_text_chunks(raw_bytes, base_metadata, max_chars_per_chunk)
    except Exception as exc:  # pragma: no cover - safety net for parser bugs
        LOGGER.warning("Multimodal parse error for %s: %s", filename, exc)
        record_mm_failure(_reason_slug(str(exc)))
        chunks = _fallback_text_chunks(raw_bytes, base_metadata, max_chars_per_chunk)
    else:
        elapsed = time.perf_counter() - start
        if timeout_s and elapsed > timeout_s:
            LOGGER.warning("Multimodal parse exceeded timeout for %s", filename)
            record_mm_failure("timeout")
            chunks = _fallback_text_chunks(raw_bytes, base_metadata, max_chars_per_chunk)

    for chunk in chunks:
        record_mm_chunk(chunk.modality, chunk.approx_bytes())
        yield chunk


def _read_all(file: IO[bytes]) -> bytes:
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        return file.read()
    except Exception as exc:  # pragma: no cover - defensive guard
        LOGGER.warning("Unable to read multimodal payload: %s", exc)
        return b""


def _simple_parse(
    raw_bytes: bytes,
    mime: str,
    base_metadata: Dict[str, str],
    max_chars_per_chunk: int,
) -> list[Chunk]:
    if mime.startswith("image/"):
        return [_build_blob_chunk("image", raw_bytes, base_metadata, 0)]

    text = _decode_bytes(raw_bytes)
    if not text:
        return [_build_blob_chunk("other", raw_bytes, base_metadata, 0)]

    pieces = list(_chunk_text(text, max_chars_per_chunk))
    chunks: list[Chunk] = []
    for index, piece in enumerate(pieces):
        metadata = {**base_metadata, "chunk_index": str(index)}
        chunks.append(Chunk(modality="text", text=piece, metadata=metadata))
    return chunks


def _fallback_text_chunks(
    raw_bytes: bytes,
    base_metadata: Dict[str, str],
    max_chars_per_chunk: int,
) -> list[Chunk]:
    decoded = _decode_bytes(raw_bytes)
    if not decoded:
        encoded = base64.b64encode(raw_bytes[:4096]).decode("ascii")
        metadata = {**base_metadata, "fallback": "binary", "chunk_index": "0"}
        return [Chunk(modality="text", text=f"[binary-fallback] {encoded}", metadata=metadata)]

    pieces = list(_chunk_text(decoded, max_chars_per_chunk))
    chunks: list[Chunk] = []
    for index, piece in enumerate(pieces):
        metadata = {
            **base_metadata,
            "chunk_index": str(index),
            "fallback": "text",
        }
        chunks.append(Chunk(modality="text", text=piece, metadata=metadata))
    return chunks


def _chunk_text(text: str, max_chars: int) -> Iterator[str]:
    limit = max(max_chars, 1)
    cursor = 0
    length = len(text)
    while cursor < length:
        yield text[cursor : cursor + limit]
        cursor += limit


def _decode_bytes(raw: bytes) -> str:
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - best effort decode
        return ""


def _build_blob_chunk(
    modality: str,
    blob: bytes,
    base_metadata: Dict[str, str],
    index: int,
) -> Chunk:
    metadata = {**base_metadata, "chunk_index": str(index)}
    return Chunk(modality=modality, blob=blob, metadata=metadata)


def _reason_slug(reason: str) -> str:
    slug = "".join(ch for ch in reason.lower() if ch.isalnum() or ch == "_")
    return slug[:64] or "unknown"
