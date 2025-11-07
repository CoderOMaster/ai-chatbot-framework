import importlib


def test_nlu_service_init_reexports():
    mod = importlib.import_module("nlu_service")
    assert hasattr(mod, "predict")
    assert hasattr(mod, "load_models")
    assert "predict" in getattr(mod, "__all__", [])
    assert "load_models" in getattr(mod, "__all__", [])