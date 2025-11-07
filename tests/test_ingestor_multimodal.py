import importlib


def test_placeholder_multimodal_present() -> None:
    module = importlib.import_module("src.ingestor.mm_adapter")
    assert hasattr(module, "iter_chunks")
