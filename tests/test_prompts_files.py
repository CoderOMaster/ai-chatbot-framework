import os

import pytest


def test_zero_shot_prompt_exists():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "app", "bot", "nlu", "llm", "prompts", "ZERO_SHOT_LEARNING_PROMPT.md")
    path = os.path.normpath(path)
    assert os.path.exists(path)


def test_lambda_prompt_exists():
    path = os.path.join(os.path.dirname(__file__), os.pardir, "lambda", "handlers", "llm", "prompts", "ZERO_SHOT_LEARNING_PROMPT.md")
    path = os.path.normpath(path)
    assert os.path.exists(path)