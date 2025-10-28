from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from collections.abc import Iterable as IterableABC, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Literal

Modalite = Literal["text", "image", "table", "formula", "other"]


@dataclass
class Chunk:
    text: str
    modality: Modalite
    meta: Dict[str, Any]


@dataclass
class MMConfig:
    parser: str = "raganything"
    max_chars_per_chunk: int = 8000
    caption_with_vlm: bool = False
    cache_dir: str = "/data/cache"
    office_enabled: bool = False
    allowed_suffixes: tuple[str, ...] | None = None
    parser_timeout: float = 15.0


def yield_chunks_from_path(path: Path, cfg: MMConfig) -> Iterator[Chunk]:
    """Yield multimodal chunks for *path* while keeping memory usage low."""

    path = path.resolve()
    os.makedirs(cfg.cache_dir, exist_ok=True)
    signature = _signature(path)
    cached_file = _cache_file(signature, cfg.cache_dir)
    if cached_file.exists():
        yield from _yield_cached(cached_file)
        return

    suffix = path.suffix.lower()
    if cfg.allowed_suffixes and suffix not in cfg.allowed_suffixes:
        raise RuntimeError(f"Extension {suffix} not enabled in this profile")
    if suffix in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"} and not cfg.office_enabled:
        raise RuntimeError("Office parsing disabled on this profile")

    content_iterable: Iterable[Dict[str, Any]] | None
    try:
        content_iterable = _parse_with_raganything(path, cfg) if cfg.parser == "raganything" else None
    except ImportError:
        content_iterable = None
    except TimeoutError:
        content_iterable = None
        _safe_warn("raganything parse timeout, falling back to text mode")
    except Exception as exc:  # pragma: no cover - best effort guard
        content_iterable = None
        _safe_warn(f"raganything parse failed: {exc}")

    if content_iterable is None:
        content_iterable = _fallback_text_only(path)

    temp_path = cached_file.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        for raw in content_iterable:
            chunk = _normalize_item(raw, cfg.max_chars_per_chunk, path)
            if not chunk.text:
                continue
            json.dump({"text": chunk.text, "modality": chunk.modality, "meta": chunk.meta}, handle, ensure_ascii=False)
            handle.write("\n")
            yield chunk
    temp_path.replace(cached_file)


def _normalize_item(item: Dict[str, Any] | Any, max_chars: int, source_hint: Path) -> Chunk:
    if isinstance(item, Mapping):
        raw_dict = dict(item)
    elif hasattr(item, "__dict__") and not isinstance(item, dict):
        raw_dict = {k: getattr(item, k) for k in dir(item) if not k.startswith("_")}
    else:
        raw_dict = {"text": str(item)}
    modality = _map_type(str(raw_dict.get("type", "text")))
    text = str(raw_dict.get("text", ""))[:max_chars]
    meta = dict(raw_dict.get("meta") or {})
    meta.setdefault("parser", "raganything")
    source_path = raw_dict.get("source_path")
    path_obj = Path(source_path) if source_path else source_hint
    meta.setdefault("source_path", path_obj.name)
    meta.setdefault("source_name", path_obj.name)
    meta.setdefault("source_tmp_path", str(source_hint))
    return Chunk(text=text, modality=modality, meta=meta)


def _fallback_text_only(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(errors="ignore")
    except Exception:
        text = ""
    return [
        {
            "type": "text",
            "text": text,
            "meta": {
                "parser": "fallback",
                "source_path": path.name,
                "source_tmp_path": str(path),
            },
        }
    ]


def _parse_with_raganything(path: Path, cfg: MMConfig) -> Iterable[Dict[str, Any]]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_invoke_raganything, path, cfg)
        try:
            return future.result(timeout=cfg.parser_timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("raganything parsing timed out") from exc


def _invoke_raganything(path: Path, cfg: MMConfig) -> Iterable[Dict[str, Any]]:
    import importlib
    import inspect

    module = importlib.import_module("raganything")
    for candidate in ("parse_to_content_list", "parse_file", "parse"):
        func_candidate = getattr(module, candidate, None)
        if not callable(func_candidate):
            continue
        func: Callable[..., Any] = func_candidate
        signature = inspect.signature(func)
        call_kwargs: Dict[str, Any] = {}
        if "path" in signature.parameters:
            call_kwargs["path"] = str(path)
        elif "filename" in signature.parameters:
            call_kwargs["filename"] = str(path)
        if "caption_with_vlm" in signature.parameters:
            call_kwargs["caption_with_vlm"] = cfg.caption_with_vlm
        try:
            result = func(**call_kwargs) if call_kwargs else func(str(path))
        except TypeError:
            result = func(str(path))
        return _ensure_iterable_payload(result)
    raise RuntimeError("raganything module does not expose a supported parser")


def _ensure_iterable_payload(result: Any) -> Iterable[Dict[str, Any]]:
    payload = result
    if isinstance(payload, dict) and "content_list" in payload:
        payload = payload["content_list"]
    if isinstance(payload, Mapping):
        return [dict(payload)]
    if isinstance(payload, IterableABC) and not isinstance(payload, (str, bytes)):
        normalized: list[Dict[str, Any]] = []
        for entry in payload:
            if isinstance(entry, Mapping):
                normalized.append(dict(entry))
            else:
                normalized.append({"text": str(entry)})
        return normalized
    return [{"text": str(payload)}]


def _signature(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    digest.update(str(int(path.stat().st_mtime)).encode("utf-8"))
    return digest.hexdigest()


def _cache_file(signature: str, cache_dir: str) -> Path:
    return Path(cache_dir) / f"{signature}.jsonl"


def _yield_cached(path: Path) -> Iterator[Chunk]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            obj = json.loads(line)
            yield Chunk(text=obj["text"], modality=_map_type(obj.get("modality", "text")), meta=obj.get("meta", {}))


def _map_type(raw: str) -> Modalite:
    raw = raw.lower()
    if raw == "text":
        return "text"
    if raw in {"image", "figure"}:
        return "image"
    if raw == "table":
        return "table"
    if raw in {"latex", "equation", "formula"}:
        return "formula"
    return "other"


def _safe_warn(message: str) -> None:
    try:
        import logging

        logging.getLogger(__name__).warning(message)
    except Exception:  # pragma: no cover
        pass
