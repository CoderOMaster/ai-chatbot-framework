import importlib
import sys
import types


def test_trainer_dry_run_prints_models_dir_and_exits_zero(monkeypatch, capsys):
    # Fake get_settings to return MODELS_DIR
    fake_common_config = types.ModuleType("ai_chatbot_common.config")
    def get_settings():
        return types.SimpleNamespace(MODELS_DIR="/models")
    fake_common_config.get_settings = get_settings
    monkeypatch.setitem(sys.modules, "ai_chatbot_common.config", fake_common_config)

    # Fake train_pipeline so it isn't actually called
    fake_utils = types.ModuleType("app.bot.nlu.pipeline_utils")
    async def train_pipeline():
        raise AssertionError("should not be called in dry run")
    fake_utils.train_pipeline = train_pipeline
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline_utils", fake_utils)

    mod = importlib.import_module("nlu_service.trainer")

    # Patch argv
    monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])    
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "dry run: would train into /models" in captured.out


def test_trainer_runs_train_pipeline_and_exits_zero(monkeypatch):
    # Fake get_settings
    fake_common_config = types.ModuleType("ai_chatbot_common.config")
    def get_settings():
        return types.SimpleNamespace(MODELS_DIR="/models")
    fake_common_config.get_settings = get_settings
    monkeypatch.setitem(sys.modules, "ai_chatbot_common.config", fake_common_config)

    # Fake train_pipeline to be awaited
    calls = {"called": False}
    fake_utils = types.ModuleType("app.bot.nlu.pipeline_utils")
    async def train_pipeline():
        calls["called"] = True
    fake_utils.train_pipeline = train_pipeline
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline_utils", fake_utils)

    mod = importlib.import_module("nlu_service.trainer")

    monkeypatch.setattr(sys, "argv", ["prog", "--train"])    
    rc = mod.main()
    assert rc == 0
    assert calls["called"] is True


def test_trainer_help_when_no_args(monkeypatch, capsys):
    # Ensure get_settings import resolves
    fake_common_config = types.ModuleType("ai_chatbot_common.config")
    def get_settings():
        return types.SimpleNamespace(MODELS_DIR="/models")
    fake_common_config.get_settings = get_settings
    monkeypatch.setitem(sys.modules, "ai_chatbot_common.config", fake_common_config)

    fake_utils = types.ModuleType("app.bot.nlu.pipeline_utils")
    async def train_pipeline():
        pass
    fake_utils.train_pipeline = train_pipeline
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline_utils", fake_utils)

    mod = importlib.import_module("nlu_service.trainer")

    monkeypatch.setattr(sys, "argv", ["prog"])    
    rc = mod.main()
    captured = capsys.readouterr()
    assert rc == 1
    assert "NLU Trainer" in captured.out
def test_trainer_models_dir_arg_sets_env(monkeypatch):
    # Fake get_settings
    fake_common_config = types.ModuleType("ai_chatbot_common.config")
    def get_settings():
        return types.SimpleNamespace(MODELS_DIR="/default")
    fake_common_config.get_settings = get_settings
    monkeypatch.setitem(sys.modules, "ai_chatbot_common.config", fake_common_config)

    # Fake train_pipeline
    fake_utils = types.ModuleType("app.bot.nlu.pipeline_utils")
    async def train_pipeline():
        return None
    fake_utils.train_pipeline = train_pipeline
    monkeypatch.setitem(sys.modules, "app.bot.nlu.pipeline_utils", fake_utils)

    mod = importlib.import_module("nlu_service.trainer")
    monkeypatch.setattr(sys, "argv", ["prog", "--train", "--models-dir", "/custom/models"])    
    rc = mod.main()
    assert rc == 0
    assert os.environ.get("MODELS_DIR") == "/custom/models"