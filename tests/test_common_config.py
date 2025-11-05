import os
from importlib import reload
import pytest
from pydantic_settings import BaseSettings  # Correct import for pydantic v2

import app.common.config as config


def test_get_settings_singleton(monkeypatch, tmp_path):
    # ensure env file not interfering
    monkeypatch.delenv('MONGODB_HOST', raising=False)

    # reset module cache
    config._settings_singleton = None
    s1 = config.get_settings()
    s2 = config.get_settings()
    assert s1 is s2
    assert hasattr(s1, 'MONGODB_HOST')


def test_settings_fields_default(monkeypatch):
    config._settings_singleton = None
    s = config.get_settings()
    assert s.MONGODB_HOST == "localhost"
    assert s.MONGODB_DATABASE == "ai_chatbot"
    assert s.MONGODB_HEALTHCHECK_RETRIES == 2


def test_settings_respects_env(monkeypatch):
    config._settings_singleton = None
    monkeypatch.setenv('MONGODB_HOST', 'db.example')
    s = config.get_settings()
    assert s.MONGODB_HOST == 'db.example'