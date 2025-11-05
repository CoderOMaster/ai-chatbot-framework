import pytest
from unittest.mock import patch
import asyncio

import nlu_service.pipeline as pipeline_mod

# Fix patch target to correct module and attribute name

def test_get_pipeline_calls_underlying():
    async def fake_get_pipeline():
        return "pipeline_obj"

    with patch("nlu_service.pipeline.get_pipeline", new=fake_get_pipeline):
        res = asyncio.run(pipeline_mod.get_pipeline())
        assert res == "pipeline_obj"


def test_predict_returns_pipeline_process_result():
    class Dummy:
        def process(self, msg):
            return {"result": "ok", "msg": msg}

    res = asyncio.run(pipeline_mod.predict({"text": "hi"}, Dummy()))
    assert res["result"] == "ok"
    assert res["msg"]["text"] == "hi"