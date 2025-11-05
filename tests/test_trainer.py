import os
import pytest
from unittest.mock import AsyncMock

import nlu_service.trainer as trainer

# Removed pytest_plugins = "pytest_asyncio" since pytest-asyncio is not installed

async def test_train_dry_run(tmp_path):
    await trainer.train(str(tmp_path), dry_run=True)
    # dry run should not create files in the target dir
    assert list(tmp_path.iterdir()) == []


async def test_train_creates_dir_and_calls_train_pipeline(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"

    async def fake_train_pipeline():
        return

    # monkeypatch the train_pipeline used inside trainer.train
    monkeypatch.setattr("app.bot.nlu.pipeline_utils.train_pipeline", fake_train_pipeline)

    async def fake_get_pipeline():
        class Dummy:
            pass

        return Dummy()

    # trainer module imported get_pipeline at module level; patch it on the trainer module
    monkeypatch.setattr("nlu_service.trainer.get_pipeline", fake_get_pipeline)

    await trainer.train(str(models_dir), dry_run=False)
    assert models_dir.exists()