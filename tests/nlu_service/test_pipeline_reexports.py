import importlib
import sys
import types


def test_pipeline_module_reexports_predict_and_load_models(monkeypatch):
    # Provide fake runtime impl to verify re-export
    fake_runtime = types.ModuleType("nlu_service.runtime")
    def predict(x):
        return {"intent": None, "entities": None}
    def load_models():
        return None
    fake_runtime.predict = predict
    fake_runtime.load_models = load_models
    fake_runtime.app = object()

    monkeypatch.setitem(sys.modules, "nlu_service.runtime", fake_runtime)

    mod = importlib.import_module("nlu_service.pipeline")
    assert mod.predict is predict
    assert mod.load_models is load_models
    assert hasattr(mod, "app")