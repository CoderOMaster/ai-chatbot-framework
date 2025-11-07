import types
import pytest

from app.bot.nlu.pipeline_utils import get_pipeline


@pytest.mark.asyncio
async def test_get_pipeline_traditional_local_when_no_forwarding(monkeypatch):
    # Ensure forwarding envs are not set
    monkeypatch.delenv('MODEL_FORWARDING_ENDPOINT', raising=False)
    monkeypatch.delenv('NLU_FORWARDING_ENDPOINT', raising=False)

    import app.bot.nlu.pipeline_utils as mod

    class DummyCfg:
        pipeline_type = 'traditional'
        class T:
            def dict(self):
                return {}
        traditional_settings = T()

    async def fake_get_nlu_config(name):
        return DummyCfg()

    async def fake_create_ml_pipeline(**kwargs):
        class P: pass
        return P()

    monkeypatch.setattr(mod, 'get_nlu_config', fake_get_nlu_config)
    monkeypatch.setattr(mod, 'create_ml_pipeline', fake_create_ml_pipeline)

    pipeline = await get_pipeline()
    assert type(pipeline).__name__ == 'P'


@pytest.mark.asyncio
async def test_get_pipeline_llm_local_when_no_forwarding(monkeypatch):
    monkeypatch.delenv('MODEL_FORWARDING_ENDPOINT', raising=False)
    monkeypatch.delenv('NLU_FORWARDING_ENDPOINT', raising=False)

    import app.bot.nlu.pipeline_utils as mod

    class DummyCfg:
        pipeline_type = 'llm'
        class L:
            def dict(self):
                return {}
        llm_settings = L()

    async def fake_get_nlu_config(name):
        return DummyCfg()

    async def fake_create_zero_shot_pipeline(**kwargs):
        class Z: pass
        return Z()

    monkeypatch.setattr(mod, 'get_nlu_config', fake_get_nlu_config)
    monkeypatch.setattr(mod, 'create_zero_shot_pipeline', fake_create_zero_shot_pipeline)

    pipeline = await get_pipeline()
    assert type(pipeline).__name__ == 'Z'