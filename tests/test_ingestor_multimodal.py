def test_placeholder_multimodal_present():
    import importlib, sys
    m = importlib.import_module("src.ingestor.mm_adapter")
    assert hasattr(m, "iter_chunks")
