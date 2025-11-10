import builtins
import importlib.util
import sys
import types
import pytest


def import_module_from_path(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_shim_imports_when_common_available(monkeypatch):
    # Create stub package and submodule with expected callables
    pkg = types.ModuleType("ai_chatbot_common")
    sub = types.ModuleType("ai_chatbot_common.database")

    def get_db():
        return "db_sentinel"

    def get_mongo_client():
        return "client_sentinel"

    async def db_dependency():
        yield "dbdep_sentinel"

    sub.get_db = get_db
    sub.get_mongo_client = get_mongo_client
    sub.db_dependency = db_dependency

    sys.modules["ai_chatbot_common"] = pkg
    sys.modules["ai_chatbot_common.database"] = sub

    mod = import_module_from_path("ai-chatbot-framework/app/database.py", name="aicf_app_database_test")

    assert mod.get_db is get_db
    assert mod.get_mongo_client is get_mongo_client
    assert mod.db_dependency is db_dependency


def test_shim_sets_none_when_common_missing(monkeypatch):
    # Ensure any existing modules are not visible to import of the target file
    sys.modules.pop("ai_chatbot_common.database", None)
    sys.modules.pop("ai_chatbot_common", None)

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: D401
        if name.startswith("ai_chatbot_common"):
            raise ModuleNotFoundError("forced missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    mod = import_module_from_path("ai-chatbot-framework/app/database.py", name="aicf_app_database_test_missing")

    assert mod.get_db is None
    assert mod.get_mongo_client is None
    assert mod.db_dependency is None