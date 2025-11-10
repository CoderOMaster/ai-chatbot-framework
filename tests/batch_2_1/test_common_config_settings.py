import importlib.util
import sys
import pytest


def import_module_from_path(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_get_settings_reads_env_and_caches(monkeypatch):
    monkeypatch.setenv("MONGODB_HOST", "mongodb://env-host:27017")
    monkeypatch.setenv("MONGODB_DATABASE", "envdb")
    monkeypatch.setenv("JWT_SECRET", "s3cr3t")
    monkeypatch.setenv("LLM_API_KEY", "key-123")
    monkeypatch.setenv("MODELS_DIR", "/tmp/models")

    mod = import_module_from_path("ai-chatbot-framework/app/common/config.py", name="aicf_common_config_test")

    # Ensure cache is clear for test isolation
    mod.get_settings.cache_clear()

    s1 = mod.get_settings()
    assert s1.MONGODB_HOST == "mongodb://env-host:27017"
    assert s1.MONGODB_DATABASE == "envdb"
    assert s1.JWT_SECRET == "s3cr3t"
    assert s1.LLM_API_KEY == "key-123"
    assert s1.MODELS_DIR == "/tmp/models"

    s2 = mod.get_settings()
    assert s1 is s2  # cached instance