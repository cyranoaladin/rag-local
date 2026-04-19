from __future__ import annotations

import importlib
import importlib.machinery
import socket
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fastapi is required") from exc


def _reload_api(monkeypatch: pytest.MonkeyPatch, env: dict[str, str] | None = None, unset: list[str] | None = None):
    mod = "src.ingestor.api"
    # Drop cached ingestor modules to re-evaluate constants from env
    for m in list(sys.modules):
        if m.startswith("src.ingestor"):
            sys.modules.pop(m)
    # default: set token unless explicitly unset
    if not unset or "INGESTOR_API_TOKEN" not in unset:
        monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    for k in (unset or []):
        monkeypatch.delenv(k, raising=False)
    return importlib.import_module(mod)


def test_timed_ollama_emb_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    class OKResp:
        status_code = 200
        text = "{\"embedding\":[0.1,0.2]}"
        def json(self):
            return {"embedding": [0.1, 0.2]}

    class BadCodeResp:
        status_code = 500
        text = "boom"
        def json(self):
            return {}

    class BadJSONResp:
        status_code = 200
        text = "not json"
        def json(self):
            raise api.requests.exceptions.JSONDecodeError("msg", "doc", 0)

    # success
    monkeypatch.setattr(api, "requests", type("R", (), {"post": lambda *a, **k: OKResp(), "exceptions": api.requests.exceptions}))
    emb = api.TimedOllamaEmbeddings(model="m", base_url="http://x")
    out = emb._process_emb_response("hello")
    assert out == [0.1, 0.2]

    # http error code
    monkeypatch.setattr(api, "requests", type("R", (), {"post": lambda *a, **k: BadCodeResp(), "exceptions": api.requests.exceptions}))
    with pytest.raises(ValueError):
        emb._process_emb_response("hello")

    # request exception
    class BoomExc(Exception):
        pass
    def raise_req_exc(*_a, **_k):
        raise api.requests.exceptions.RequestException("netfail")
    monkeypatch.setattr(api, "requests", type("R", (), {"post": raise_req_exc, "exceptions": api.requests.exceptions}))
    with pytest.raises(ValueError):
        emb._process_emb_response("hello")

    # bad json
    monkeypatch.setattr(api, "requests", type("R", (), {"post": lambda *a, **k: BadJSONResp(), "exceptions": api.requests.exceptions}))
    with pytest.raises(ValueError):
        emb._process_emb_response("hello")


def test_validate_remote_url_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    with pytest.raises(api.HTTPException):
        api._validate_remote_url("ftp://example.com")
    with pytest.raises(api.HTTPException):
        api._validate_remote_url("http://")

    # DNS failure
    monkeypatch.setattr(api.socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("no dns")))
    with pytest.raises(api.HTTPException):
        api._validate_remote_url("http://example.com")

    # Private IP returned
    def fake_getaddrinfo(*_a, **_k):
        return [(None, None, None, None, ("192.168.1.10", 80))]
    monkeypatch.setattr(api.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(api.HTTPException):
        api._validate_remote_url("http://example.com")


def test_download_to_temp_max_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # shrink max bytes via env and reimport
    api = _reload_api(monkeypatch, env={"MAX_REMOTE_BYTES": "10"})

    class FakeResp:
        def __init__(self):
            self.headers = {}
            self.status_code = 200
            self.encoding = "utf-8"
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b"12345678"
            yield b"12345678"  # exceed limit
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_get(url, timeout=30, stream=True, headers=None):  # noqa: ARG001
        return FakeResp()

    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": fake_get, "RequestException": api.requests.RequestException}))
    with pytest.raises(api.HTTPException):
        api._download_to_temp("http://example.com/file.pdf", ".pdf")


def test_fetch_remote_text_limits_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, env={"MAX_REMOTE_BYTES": "5"})

    # Declared length too big
    class DeclaredTooBig:
        def __init__(self):
            self.headers = {"content-length": "10"}
            self.history = []
            self.url = "http://example.com"
            self.encoding = "utf-8"
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b"hi"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    # Empty content
    class EmptyResp:
        def __init__(self):
            self.headers = {}
            self.history = []
            self.url = "http://example.com/x"
            self.encoding = "utf-8"
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b""
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def get_declared(*_a, **_k):
        return DeclaredTooBig()
    def get_empty(*_a, **_k):
        return EmptyResp()

    def get_declared_with_headers(*_a, headers=None, **_k):
        return DeclaredTooBig()
    def get_empty_with_headers(*_a, headers=None, **_k):
        return EmptyResp()

    # declared length branch
    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": get_declared_with_headers, "RequestException": api.requests.RequestException}))
    with pytest.raises(api.HTTPException):
        api._fetch_remote_text("http://example.com")

    # empty content branch
    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": get_empty_with_headers, "RequestException": api.requests.RequestException}))
    with pytest.raises(api.HTTPException):
        api._fetch_remote_text("http://example.com")


def test_load_from_url_pdf_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch)

    # fake temp file path returned
    fake_pdf = tmp_path / "x.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4\n...")
    monkeypatch.setattr(api, "_download_to_temp", lambda url, suffix: fake_pdf)

    class FakeLoader:
        def __init__(self, path: str):  # noqa: ARG002
            pass
        def load(self):
            return [api.Document(page_content="pdf", metadata={"source": "x"})]

    monkeypatch.setattr(api, "PyPDFLoader", FakeLoader)
    docs = api.load_from_url("http://example.com/file.pdf")
    assert docs and docs[0].page_content == "pdf"


def test_load_docx_partition_and_basic_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch)

    # Simulate unstructured.partition.docx.partition_docx
    pkg = types.ModuleType("unstructured")
    sub = types.ModuleType("unstructured.partition")
    subdocx = types.ModuleType("unstructured.partition.docx")

    class Meta:
        def __init__(self, d):
            self._d = d
        def to_dict(self):
            return self._d
    class Elem:
        def __init__(self, text, meta):
            self.text = text
            self.metadata = meta

    def part_ok(filename=None, include_metadata=True):  # noqa: ARG002
        return [Elem("A", Meta({"k": "v"})), Elem("", Meta({}))]

    subdocx.partition_docx = part_ok
    pkg.partition = sub
    monkeypatch.setitem(sys.modules, "unstructured", pkg)
    monkeypatch.setitem(sys.modules, "unstructured.partition", sub)
    monkeypatch.setitem(sys.modules, "unstructured.partition.docx", subdocx)

    docs = api.load_docx(str(tmp_path / "file.docx"))
    assert docs and docs[0].page_content == "A"
    assert docs[0].metadata.get("k") == "v"
    assert docs[0].metadata.get("source") == "file.docx"
    assert docs[0].metadata.get("mime_type")

    # Now force partition_docx to error -> fallback to basic loader
    docx_mod = types.ModuleType("docx")
    class _Paragraph:
        def __init__(self, text):
            self.text = text
    class _Document:
        def __init__(self, path):  # noqa: ARG002
            self.paragraphs = [_Paragraph("L1"), _Paragraph("")]
    docx_mod.Paragraph = _Paragraph
    docx_mod.Document = _Document
    docx_mod.__spec__ = importlib.machinery.ModuleSpec(name="docx", loader=None)
    monkeypatch.setitem(sys.modules, "docx", docx_mod)

    def part_fail(*_a, **_k):
        raise RuntimeError("fail")
    subdocx.partition_docx = part_fail

    docs2 = api.load_docx(str(tmp_path / "other.docx"))
    assert docs2 and docs2[0].page_content == "L1"


def test_fetch_remote_text_redirect_and_req_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    class Hop:
        def __init__(self, url):
            self.url = url
    class Resp:
        def __init__(self, url, history):
            self.headers = {}
            self.encoding = "utf-8"
            self.url = url
            self.history = history
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b"hi"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def get_bad_history(*_a, **_k):
        return Resp("http://final", [Hop("ftp://bad")])

    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": get_bad_history, "RequestException": api.requests.RequestException}))
    with pytest.raises(api.HTTPException):
        api._fetch_remote_text("http://example.com")

    def raise_req(*_a, **_k):
        raise api.requests.RequestException("boom")
    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": raise_req, "RequestException": api.requests.RequestException}))
    with pytest.raises(api.HTTPException):
        api._fetch_remote_text("http://example.com")


def test_load_source_documents_pdf_docx_unknown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path)})

    # pdf local
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4\n...")
    class PL:
        def __init__(self, path):  # noqa: ARG002
            pass
        def load(self):
            return [api.Document(page_content="p", metadata={})]
    monkeypatch.setattr(api, "PyPDFLoader", PL)
    pdf_docs = api._load_source_documents(api.IngestRequest(source_type="pdf", source=str(p)))
    assert pdf_docs and pdf_docs[0].page_content == "p"

    # docx local
    monkeypatch.setattr(api, "load_docx", lambda path: [api.Document(page_content="d", metadata={})])
    d = tmp_path / "b.docx"
    d.write_text("x", encoding="utf-8")
    docx_docs = api._load_source_documents(api.IngestRequest(source_type="docx", source=str(d)))
    assert docx_docs and docx_docs[0].page_content == "d"

    # unknown source type is rejected by pydantic validation
    with pytest.raises(ValidationError):
        api.IngestRequest(source_type="unknown", source="x")


def test_ingest_mode_unsupported_and_loader_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path)})
    f = tmp_path / "c.md"
    f.write_text("ok", encoding="utf-8")

    client = TestClient(api.app)
    r = client.post("/ingest?mode=binary", json={"source_type":"markdown","source": f.name}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 400

    # loader raises generic error -> 500 wrapper
    monkeypatch.setattr(api, "_load_source_documents", lambda req: (_ for _ in ()).throw(RuntimeError("oops")))
    r2 = client.post("/ingest", json={"source_type":"markdown","source": f.name}, headers={"Authorization":"Bearer tok"})
    assert r2.status_code == 500


def test_embedding_valueerror_non_404_causes_500(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    # prepare a doc
    monkeypatch.setattr(api, "_load_source_documents", lambda req: [api.Document(page_content="abc", metadata={"source":"u"})])

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}
        def add(self, **_):
            return None

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class BadEmb:
        def __init__(self, *a, **k):
            pass
        def embed_documents(self, docs):
            raise ValueError("bad")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", BadEmb)

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source":"x.md"}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 500


def test_download_to_temp_skips_empty_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    class Resp:
        def __init__(self):
            self.headers = {}
            self.status_code = 200
            self.encoding = "utf-8"
        def raise_for_status(self):
            return None
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b""
            yield b"abc"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": lambda *a, **k: Resp(), "RequestException": api.requests.RequestException}))
    p = api._download_to_temp("http://example.com/file.txt", ".txt")
    assert p.exists()
    try:
        p.unlink()
    except OSError:
        pass


def test_fetch_remote_text_success_with_history(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    # avoid real DNS
    monkeypatch.setattr(api, "_validate_remote_url", lambda url: None)

    class Hop:
        def __init__(self, url):
            self.url = url
    class R:
        def __init__(self):
            self.headers = {}
            self.encoding = "utf-8"
            self.url = "http://final"
            self.history = [Hop("http://intermediate")]
        def iter_content(self, chunk_size=8192):  # noqa: ARG002
            yield b"hello"
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(api, "requests", type("Rq", (), {"get": lambda *a, **k: R(), "RequestException": api.requests.RequestException}))
    final, text = api._fetch_remote_text("http://example.com")
    assert final == "http://final" and text.strip() == "hello"


def test_load_from_url_empty_html(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    monkeypatch.setattr(api, "_fetch_remote_text", lambda url: ("http://x", "<html></html>"))
    class FakeSoup:
        def __init__(self, t, parser):  # noqa: ARG002
            pass
        def get_text(self, *a, **k):
            return ""
    monkeypatch.setattr(api, "BeautifulSoup", FakeSoup)
    with pytest.raises(api.HTTPException):
        api.load_from_url("http://x")


def test_gdrive_service_account_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, env={"GOOGLE_APPLICATION_CREDENTIALS": "/nope/missing.json"})
    with pytest.raises(api.HTTPException):
        api._load_source_documents(api.IngestRequest(source_type="gdrive_folder", source="folder"))


def test_gdrive_default_credentials_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch)
    # point HOME to a temp dir with no ~/.credentials/credentials.json
    monkeypatch.setattr(api.Path, "home", lambda: tmp_path)
    with pytest.raises(api.HTTPException):
        api._load_source_documents(api.IngestRequest(source_type="gdrive_folder", source="folder"))


def test_gdrive_loader_valueerror_wrap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch)
    # Create default creds file
    home = tmp_path / "home"
    creds_dir = home / ".credentials"
    creds_dir.mkdir(parents=True, exist_ok=True)
    (creds_dir / "credentials.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(api.Path, "home", lambda: home)

    class GL:
        def __init__(self, **kwargs):  # noqa: D401, ARG002
            raise ValueError("bad cfg")
    monkeypatch.setattr(api, "GoogleDriveLoader", GL)

    with pytest.raises(api.HTTPException):
        api._load_source_documents(api.IngestRequest(source_type="gdrive_folder", source="folder"))


def test_prepare_chunks_for_chroma_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)
    docs = [
        api.Document(page_content="same", metadata={"modality": "text", "k": "1"}),
        api.Document(page_content="same", metadata={"modality": "text", "k": "2"}),
        api.Document(page_content="other", metadata={}),
    ]
    req = api.IngestRequest(source_type="markdown", source="x")
    batch = api._prepare_chunks_for_chroma(req, docs)
    assert len(batch.ids) == 2 and batch.modality == "text"


def test_prepare_multimodal_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    class SChunk:
        def __init__(self, text, modality, metadata=None):
            self.text = text
            self.modality = modality
            self.metadata = metadata or {}
        def as_text(self):
            return self.text

    chunks = [
        SChunk("hello", "image", {"a": 1}),
        SChunk("hello", "image", {"a": 1}),  # duplicate
        SChunk("world", "text", {}),
    ]
    req = api.IngestRequest(source_type="markdown", source="x")
    batch = api._prepare_multimodal_chunks(req, chunks)
    assert len(batch.ids) == 2 and batch.modality in {"image", "text"}


def test_extract_pdf_documents_from_bytes_falls_back_to_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)

    class _Page:
        def extract_text(self) -> str:
            return ""

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(api.pdfplumber, "open", lambda *_args, **_kwargs: _Pdf())
    monkeypatch.setattr(api, "_ocr_pdf_bytes", lambda *_args, **_kwargs: ["Texte OCR page 1"])

    docs = api._extract_pdf_documents_from_bytes(b"%PDF-1.4", "scan.pdf")

    assert len(docs) == 1
    assert docs[0].page_content == "Texte OCR page 1"
    assert docs[0].metadata["source"] == "scan.pdf"


def test_documents_have_text_ignores_blank_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch)
    blank_doc = api.Document(page_content="   ", metadata={})
    text_doc = api.Document(page_content="Texte utile", metadata={})

    assert api._documents_have_text([]) is False
    assert api._documents_have_text([blank_doc]) is False
    assert api._documents_have_text([blank_doc, text_doc]) is True


def test_load_markdown_empty_and_unreadable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch)
    # empty file
    empty = tmp_path / "a.md"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(api.HTTPException):
        api.load_markdown(empty)
    # unreadable (directory -> OSError from read_text)
    with pytest.raises(api.HTTPException):
        api.load_markdown(tmp_path)


def test_resolve_local_path_variants(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    # Base root
    api = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path)})

    # not found
    with pytest.raises(api.HTTPException):
        api._resolve_local_path("missing.txt")

    # not a file
    d = tmp_path / "sub"
    d.mkdir()
    with pytest.raises(api.HTTPException):
        api._resolve_local_path("sub")

    # allow unrestricted absolute path outside root
    outside_dir = tmp_path_factory.mktemp("outside")
    outside_file = outside_dir / "z.txt"
    outside_file.write_text("x", encoding="utf-8")
    api2 = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path), "ALLOW_UNRESTRICTED_LOCAL": "true"})
    p = api2._resolve_local_path(str(outside_file))
    assert p.exists() and p.is_file()


def test_client_ip_and_ip_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, unset=["INGESTOR_API_TOKEN"])  # no token check

    class Req:
        def __init__(self, headers: dict[str, str] | None = None, host: str | None = None):
            self.headers = headers or {}
            self.client = type("C", (), {"host": host})()

    # X-Forwarded-For path
    assert api._get_client_ip(Req(headers={"X-Forwarded-For": "1.2.3.4"})) == "1.2.3.4"
    # client.host fallback
    assert api._get_client_ip(Req(host="5.6.7.8")) == "5.6.7.8"

    # allowlist None -> allowed
    assert api._ip_allowed("1.2.3.4", None) is True
    # invalid ip string
    assert api._ip_allowed("bad-ip", "1.2.3.0/24") is False
    # invalid cidr entries ignored
    assert api._ip_allowed("1.2.3.4", "notA, 1.2.3.0/24") is True

    # enforce security with restrictive allowlist -> forbidden
    monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "10.0.0.0/8")
    with pytest.raises(api.HTTPException):
        api._enforce_security(Req(host="1.2.3.4"), None)


def test_multimodal_disabled_and_metrics_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path)})
    # Prepare a markdown doc to avoid loader errors
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")

    client = TestClient(api.app)
    # multimodal disabled
    r = client.post("/ingest?mode=multimodal", json={"source_type": "markdown", "source": f.name}, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 400

    # metrics enabled path
    api.ingest_metrics.METRICS_ENABLED = True
    r = client.get("/metrics")
    assert r.status_code == 200


def test_x_api_token_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _reload_api(monkeypatch, env={"LOCAL_SOURCE_ROOT": str(tmp_path)})
    f = tmp_path / "b.md"
    f.write_text("hello", encoding="utf-8")

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}
        def add(self, **_):
            return None
    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", lambda *a, **k: type("E", (), {"embed_documents": lambda _s, docs: [[0.0] * 3 for _ in docs]})())

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source": f.name}, headers={"X-API-Token":"tok"})
    assert r.status_code == 200
