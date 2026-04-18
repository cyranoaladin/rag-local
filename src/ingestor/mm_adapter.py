"""Multimodal parsing helpers with lightweight caching and metrics hooks."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import inspect as _inspect
import io
import json
import os
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, BinaryIO

__all__ = [
    "Chunk",
    "parse_multimodal",
    "iter_chunks",
]


def _metrics() -> ModuleType:
    module_name = "src.ingestor.metrics"
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(__file__).with_name("metrics.py"),
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    raise ImportError("Unable to load metrics module")


# Python 3.9 compatibility: dataclass(slots=...) not available before 3.10
if "slots" in _inspect.signature(dataclass).parameters:
    _DATACLASS_DECORATOR = dataclass
    _DATACLASS_KW = {"slots": True}
else:  # pragma: no cover - runtime on older Python
    def _dataclass_compat(*d_args, **d_kwargs):
        d_kwargs.pop("slots", None)
        return dataclass(*d_args, **d_kwargs)
    _DATACLASS_DECORATOR = _dataclass_compat
    _DATACLASS_KW = {}

@_DATACLASS_DECORATOR(**_DATACLASS_KW)
class Chunk:
    """Represents a multimodal payload emitted by the parser."""

    modality: str
    text: str | None = None
    blob: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_text(self) -> str:
        if self.text:
            return self.text
        if self.blob:
            try:
                return self.blob.decode("utf-8", errors="ignore")
            except AttributeError:
                return ""
        return ""

    def approx_bytes(self) -> int:
        if self.blob:
            return len(self.blob)
        if self.text:
            return len(self.text.encode("utf-8"))
        return 0

    def for_cache(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "modality": self.modality,
            "text": self.text,
            "metadata": self.metadata,
        }
        if self.blob is not None:
            payload["blob_b64"] = base64.b64encode(self.blob).decode("ascii")
        return payload

    @classmethod
    def from_cache(cls, payload: dict[str, Any]) -> Chunk:
        blob_data = payload.get("blob_b64")
        blob = base64.b64decode(blob_data) if isinstance(blob_data, str) else None
        metadata = payload.get("metadata") or {}
        return cls(  # type: ignore[call-arg]
            modality=str(payload.get("modality", "unknown")),
            text=payload.get("text"),
            blob=blob,
            metadata=dict(metadata),
        )


DEFAULT_CACHE_DIR = "/data/mm-cache"


def parse_multimodal(
    handle: BinaryIO,
    *,
    filename: str,
    mime: str,
    timeout_s: float,
    max_chars_per_chunk: int,
    cache_dir: str | Path,
) -> Iterator[Chunk]:
    """Parse a binary payload into modality-aware chunks.

    The implementation keeps memory usage modest while still offering a simple
    caching strategy keyed by payload hash and mtime so repeated ingests avoid
    reprocessing work. When parsing exceeds the provided timeout the function
    records a failure metric but falls back to text-only extraction so the ingest
    pipeline retains best-effort behaviour.
    """

    cache_root = Path(cache_dir or DEFAULT_CACHE_DIR)
    cache_root.mkdir(parents=True, exist_ok=True)

    metrics_module = _metrics()

    with metrics_module.track_mm_parse_latency():
        raw_bytes, timed_out = _read_payload(handle, timeout_s)
        if timed_out:
            metrics_module.record_mm_failure("timeout")

        metadata = _base_metadata(handle, filename, mime)
        cache_entry = _load_from_cache(cache_root, raw_bytes, metadata["source_mtime"])
        if cache_entry:
            for idx, cached_payload in enumerate(cache_entry, start=0):
                chunk = Chunk.from_cache(cached_payload)
                chunk.metadata.setdefault("chunk_index", str(idx))
                chunk.metadata.setdefault("filename", metadata["filename"])
                chunk.metadata.setdefault("mime_type", metadata["mime_type"])
                chunk.metadata.setdefault("cached", "true")
                metrics_module.record_mm_chunk(chunk.modality, chunk.approx_bytes())
                yield chunk
            return

        text = _decode_to_text(raw_bytes, mime)
        if not text:
            if raw_bytes:
                yield from _emit_blob_chunks(raw_bytes, metadata, metrics_module)
            else:
                metrics_module.record_mm_failure("empty_payload")
            return

        max_chars = max(1, int(max_chars_per_chunk or 0))
        chunks = list(_split_text(text, max_chars))
        if not chunks:
            metrics_module.record_mm_failure("empty_payload")
            return

        emitted: list[dict[str, Any]] = []
        for idx, snippet in enumerate(chunks, start=0):
            chunk = Chunk(  # type: ignore[call-arg]
                modality="text",
                text=snippet,
                metadata={
                    "chunk_index": str(idx),
                    "filename": metadata["filename"],
                    "mime_type": metadata["mime_type"],
                    "cached": "false",
                },
            )
            if timed_out:
                chunk.metadata["parse_timeout"] = "true"
            metrics_module.record_mm_chunk(chunk.modality, chunk.approx_bytes())
            emitted.append(chunk.for_cache())
            yield chunk

        _persist_cache(cache_root, raw_bytes, metadata["source_mtime"], emitted)


# Legacy compatibility alias (maintains old import path expected by tests and
# external automation). The implementation now simply delegates to
# parse_multimodal while keeping the streaming contract unchanged.
def iter_chunks(*args, **kwargs):
    return parse_multimodal(*args, **kwargs)


def _read_payload(stream: BinaryIO, timeout_s: float) -> tuple[bytes, bool]:
    if timeout_s is not None and timeout_s <= 0:
        _rewind(stream)
        data = stream.read()
        return (data if isinstance(data, bytes) else b""), True

    start = time.perf_counter()
    parts: list[bytes] = []
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        parts.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
    duration = time.perf_counter() - start
    timed_out = bool(timeout_s and duration > timeout_s)
    _rewind(stream)
    return (b"".join(parts), timed_out)


def _rewind(stream: BinaryIO) -> None:
    try:
        stream.seek(0)
    except (OSError, AttributeError, io.UnsupportedOperation):
        pass


def _base_metadata(stream: BinaryIO, filename: str, mime: str) -> dict[str, Any]:
    mtime: str = "unknown"
    fileno = getattr(stream, "fileno", None)
    if callable(fileno):
        try:
            stat = os.fstat(fileno())
            mtime = str(int(stat.st_mtime))
        except (OSError, io.UnsupportedOperation):
            mtime = "unknown"
    return {
        "filename": filename or "unknown",
        "mime_type": mime or "application/octet-stream",
        "source_mtime": mtime,
    }


def _decode_to_text(payload: bytes, mime: str) -> str:
    if not payload:
        return ""
    mime_lower = (mime or "").lower()

    # Text-based formats: decode directly
    if mime_lower.startswith("text/") or mime_lower in {"application/json", "application/xml"}:
        return payload.decode("utf-8", errors="ignore")

    # Images: OCR via pytesseract
    if mime_lower.startswith("image/"):
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(io.BytesIO(payload))
            # Try French first, fallback to English
            try:
                text = pytesseract.image_to_string(img, lang="fra+eng")
            except Exception:
                text = pytesseract.image_to_string(img, lang="eng")
            return (text or "").strip()
        except ImportError:
            pass  # pytesseract not installed, fall through
        except Exception:
            pass

    # PDFs: extract text via pdfplumber or pypdf
    if mime_lower == "application/pdf":
        try:
            import pdfplumber
            text_parts: list[str] = []
            with pdfplumber.open(io.BytesIO(payload)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n".join(text_parts)
        except ImportError:
            pass
        except Exception:
            pass
        # Fallback to pypdf
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(payload))
            return "\n".join(
                (page.extract_text() or "") for page in reader.pages
            )
        except Exception:
            pass

    # Audio: try whisper transcription if available
    if mime_lower.startswith("audio/") or mime_lower.startswith("video/"):
        try:
            import tempfile

            import whisper
            with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            model = whisper.load_model("base")
            result = model.transcribe(tmp_path, language="fr")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return (result.get("text", "") or "").strip()
        except ImportError:
            pass  # whisper not installed
        except Exception:
            pass

    # Fallback: try decoding as UTF-8
    return payload.decode("utf-8", errors="ignore")


def _split_text(text: str, max_chars: int) -> Iterable[str]:
    text = text.strip()
    if not text:
        return []
    return (text[i : i + max_chars] for i in range(0, len(text), max_chars))


def _emit_blob_chunks(payload: bytes, metadata: dict[str, Any], metrics_module: ModuleType) -> Iterator[Chunk]:
    chunk = Chunk(  # type: ignore[call-arg]
        modality="other",
        blob=payload,
        metadata={
            "chunk_index": "0",
            "filename": metadata["filename"],
            "mime_type": metadata["mime_type"],
            "cached": "false",
        },
    )
    metrics_module.record_mm_chunk(chunk.modality, chunk.approx_bytes())
    yield chunk


def _hash_payload(payload: bytes, mtime: str) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    if mtime and mtime != "unknown":
        return f"{digest}-{mtime}"
    return digest


def _cache_path(root: Path, payload: bytes, mtime: str) -> Path:
    key = _hash_payload(payload, mtime)
    return root / f"{key}.json"


def _load_from_cache(root: Path, payload: bytes, mtime: str) -> list[dict[str, Any]] | None:
    path = _cache_path(root, payload, mtime)
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cached, list):
            return cached
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _persist_cache(root: Path, payload: bytes, mtime: str, emitted: list[dict[str, Any]]) -> None:
    if not emitted:
        return
    path = _cache_path(root, payload, mtime)
    try:
        path.write_text(json.dumps(emitted), encoding="utf-8")
    except OSError:
        pass
