import asyncio
from importlib import reload
from types import SimpleNamespace
import pytest
import sys


def test_parse_args_defaults(monkeypatch):
    import app.nlu_service.trainer as trainer
    reload(trainer)

    # No CLI args -> expect defaults
    monkeypatch.setenv("MODEL_DIR", "/models-default")
    monkeypatch.setattr(sys, "argv", ["prog"])  # simulate no args
    args = trainer.parse_args()
    assert args.models_dir == "/models-default"
    assert args.train is False
    assert args.dry_run is False


def test_main_dry_run_logs_and_returns(monkeypatch, caplog):
    import app.nlu_service.trainer as trainer
    reload(trainer)

    # Build args with dry_run
    args = SimpleNamespace(dry_run=True, train=False)

    # Run _main directly and ensure it returns without calling train_pipeline
    called = {"train": False}

    async def fake_train_pipeline():
        called["train"] = True

    monkeypatch.setattr("app.bot.nlu.pipeline_utils.train_pipeline", fake_train_pipeline)

    caplog.set_level("INFO", logger="nlu_trainer")
    asyncio.run(trainer._main(args))

    assert called["train"] is False
    assert any("trainer dry run ok" in r.message for r in caplog.records)


def test_main_train_invokes_train_pipeline_and_logs(monkeypatch, caplog):
    import app.nlu_service.trainer as trainer
    reload(trainer)

    args = SimpleNamespace(dry_run=False, train=True)

    called = {"train": False}

    async def fake_train_pipeline():
        called["train"] = True

    monkeypatch.setattr("app.bot.nlu.pipeline_utils.train_pipeline", fake_train_pipeline)

    caplog.set_level("INFO", logger="nlu_trainer")
    asyncio.run(trainer._main(args))

    assert called["train"] is True
    assert any("training complete" in r.message for r in caplog.records)


def test_main_no_flags_logs_nothing_to_do(monkeypatch, caplog):
    import app.nlu_service.trainer as trainer
    reload(trainer)

    # Simulate parse_args returning neither train nor dry_run
    def fake_parse_args():
        return SimpleNamespace(dry_run=False, train=False)

    monkeypatch.setattr(trainer, "parse_args", fake_parse_args)

    caplog.set_level("INFO", logger="nlu_trainer")
    trainer.main()

    assert any("nothing to do; pass --train or --dry_run" in r.message for r in caplog.records)