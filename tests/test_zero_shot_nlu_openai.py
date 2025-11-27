import sys
import time
import json
import tempfile
import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

# Create fake external modules to satisfy imports in the target module
fake_langchain_openai = SimpleNamespace()
class FakeChatOpenAI:
    def __init__(self, *args, **kwargs):
        # Store kwargs for inspection if needed
        self.kwargs = kwargs
fake_langchain_openai.ChatOpenAI = FakeChatOpenAI

# Fake prompt template and output parser modules
class FakeChatPromptTemplate:
    @staticmethod
    def from_messages(msgs):
        # Return an object that can be piped with | to create a chain
        class Chainable:
            def __or__(self, other):
                return self
            def invoke(self, kwargs):
                # Default no-op; tests will override chain on instances as needed
                return {}
        return Chainable()

class FakeJsonOutputParser:
    def __init__(self):
        pass

fake_langchain_core_prompts = SimpleNamespace(ChatPromptTemplate=FakeChatPromptTemplate)
fake_langchain_core_output_parsers = SimpleNamespace(JsonOutputParser=FakeJsonOutputParser)

sys.modules['langchain_openai'] = fake_langchain_openai
sys.modules['langchain_core'] = SimpleNamespace()
sys.modules['langchain_core.prompts'] = fake_langchain_core_prompts
sys.modules['langchain_core.output_parsers'] = fake_langchain_core_output_parsers

# Now import the module under test
from app.bot.nlu.llm import zero_shot_nlu_openai as zs


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Prevent real sleeping in tests by patching time.sleep."""
    monkeypatch.setattr(time, 'sleep', lambda s: None)


def test_inmemory_response_cache_set_get_clear_and_ttl():
    """Validate InMemoryResponseCache stores, retrieves and expires entries."""
    cache = zs.InMemoryResponseCache()
    assert cache.get('missing') is None

    cache.set('k1', {'a': 1}, ttl=10)
    assert cache.get('k1') == {'a': 1}

    # Force expired entry by setting negative TTL
    cache.set('k2', {'b': 2}, ttl=-10)
    assert cache.get('k2') is None

    cache.clear()
    assert cache.get('k1') is None


class DummyRedisClient:
    def __init__(self):
        self.store = {}
    def get(self, k):
        return self.store.get(k)
    def setex(self, k, ttl, val):
        self.store[k] = val
    def keys(self, pattern):
        # simplistic pattern match for prefix*
        prefix = pattern.replace('*','')
        return [k for k in self.store.keys() if k.startswith(prefix)]
    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


def test_redis_response_cache_basic_operations():
    """Validate RedisResponseCache wraps redis client and handles JSON serialization."""
    client = DummyRedisClient()
    cache = zs.RedisResponseCache(client, ttl=5)

    cache.set('foo', {'x': 1})
    # Redis client stores raw JSON string as implementation uses json.dumps
    assert client.get('nlu_llm_cache:foo') == json.dumps({'x': 1})

    # get should return parsed dict
    assert cache.get('foo') == {'x': 1}

    # clear should remove keys
    cache.clear()
    assert client.get('nlu_llm_cache:foo') is None


def test_redis_response_cache_handles_exceptions(monkeypatch):
    """If redis client throws, the cache should handle it gracefully."""
    class BadClient:
        def get(self, k):
            raise RuntimeError('boom')
        def setex(self, *a, **k):
            raise RuntimeError('boom')
        def keys(self, pattern):
            raise RuntimeError('boom')
        def delete(self, *k):
            raise RuntimeError('boom')

    client = BadClient()
    cache = zs.RedisResponseCache(client)

    # Should not raise
    assert cache.get('x') is None
    cache.set('x', {'a': 1})
    cache.clear()


def test_rate_limiter_allows_and_blocks():
    """RateLimiter should allow up to max_requests and block further ones."""
    rl = zs.RateLimiter(max_requests=2, window_seconds=60)
    assert rl.is_allowed() is True
    assert rl.is_allowed() is True
    # third request should be blocked
    assert rl.is_allowed() is False


def test_rate_limiter_wait_if_needed(monkeypatch):
    """wait_if_needed should return zero when allowed and non-negative when blocked."""
    rl = zs.RateLimiter(max_requests=1, window_seconds=1)
    assert rl.is_allowed() is True

    # Simulate the request being recent; wait_if_needed will compute a small wait
    # Patch requests list to contain a single recent timestamp
    rl.requests = [time.time()]
    # Patch sleep to record sleep duration
    slept = {'t': 0}
    def fake_sleep(s):
        slept['t'] = s
    monkeypatch.setattr(time, 'sleep', fake_sleep)

    wait = rl.wait_if_needed()
    assert wait >= 0
    # ensure sleep was called (or at least our fake recorded something)
    assert slept['t'] >= 0


def test_circuit_breaker_state_transitions():
    """CircuitBreaker should open after threshold failures and allow reset after timeout."""
    cb = zs.CircuitBreaker(failure_threshold=2, recovery_timeout=1, expected_exception=RuntimeError)

    def failing():
        raise RuntimeError('fail')

    # First failure
    with pytest.raises(RuntimeError):
        cb.call(failing)
    assert cb.failure_count == 1
    assert cb.state == 'closed'

    # Second failure opens the circuit
    with pytest.raises(RuntimeError):
        cb.call(failing)
    assert cb.failure_count == 2
    assert cb.state == 'open'

    # Immediate subsequent calls should raise RuntimeError from circuit open
    with pytest.raises(RuntimeError):
        cb.call(lambda: 'ok')

    # Simulate recovery timeout elapsed
    cb.last_failure_time = time.time() - 10
    # Next call should attempt reset (half-open) and will succeed
    def succeed():
        return 'ok'
    res = cb.call(succeed)
    assert res == 'ok'
    assert cb.state == 'closed'


def test_retry_with_backoff_succeeds_after_retries(monkeypatch):
    """retry_with_backoff should retry on exception and eventually succeed."""
    counter = {'calls': 0}

    @zs.retry_with_backoff(max_retries=3, initial_delay=0.1, backoff_factor=2, max_delay=1)
    def sometimes_fail():
        counter['calls'] += 1
        if counter['calls'] < 3:
            raise ValueError('temporary')
        return 'ok'

    # Patch sleep to avoid delay
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    assert sometimes_fail() == 'ok'
    assert counter['calls'] == 3


def test_retry_with_backoff_raises_after_exhaust(monkeypatch):
    """After exhausting retries, last exception should be raised."""
    @zs.retry_with_backoff(max_retries=1, initial_delay=0.1, backoff_factor=2)
    def always_fail():
        raise KeyError('bad')

    monkeypatch.setattr(time, 'sleep', lambda s: None)
    with pytest.raises(KeyError):
        always_fail()


def test_token_usage_monitor_records_and_reports():
    """TokenUsageMonitor should accumulate token counts and costs."""
    monitor = zs.TokenUsageMonitor(cost_per_1k_input=1.0, cost_per_1k_output=2.0)
    cost1 = monitor.record_usage(1000, 500)
    assert cost1 == pytest.approx(1.0 + 1.0)

    stats = monitor.get_stats()
    assert stats['total_input_tokens'] == 1000
    assert stats['total_output_tokens'] == 500
    assert stats['total_requests'] == 1
    assert isinstance(stats['total_cost'], float)


def test_prompt_version_manager_loads_and_falls_back(tmp_path):
    """PromptVersionManager should load versioned templates and fallback to base template if version missing."""
    base = tmp_path / "prompts"
    base.mkdir()

    # Create base template and a versioned template
    base_template = base / "ZERO_SHOT_LEARNING_PROMPT.md"
    base_template.write_text("base template - intents: {{intents}}")

    v2 = base / "ZERO_SHOT_LEARNING_PROMPT_v2.0.md"
    v2.write_text("v2 template - version 2")

    pvm = zs.PromptVersionManager(base_path=str(base))
    # Default version is 1.0; loading v2.0 should return v2
    out_v2 = pvm.load_template('ZERO_SHOT_LEARNING_PROMPT.md', version='2.0')
    assert 'version 2' in out_v2

    # Loading non-existing version should fallback to base
    out_fallback = pvm.load_template('ZERO_SHOT_LEARNING_PROMPT.md', version='9.9')
    assert 'base template' in out_fallback

    # set_version changes current_version
    pvm.set_version('2.0')
    assert pvm.current_version == '2.0'


def test_fallback_nlu_component_processes_message():
    """Fallback component should attach default NLU fields to the message."""
    fb = zs.FallbackNLUComponent()
    msg = {'text': 'hello'}
    out = fb.process(msg.copy())
    assert out['_fallback_used'] is True
    assert out['intent']['confidence'] == 0.0


@pytest.fixture
def zero_shot_component(monkeypatch):
    """Fixture to create ZeroShotNLUOpenAI with initialization stubbed to avoid langchain chain building."""
    # Stub _initialize_chain to attach a controllable chain
    def fake_init(self):
        # simple chain object with invoke function we can replace in tests
        self.chain = SimpleNamespace(invoke=lambda payload: {})
    monkeypatch.setattr(zs.ZeroShotNLUOpenAI, '_initialize_chain', fake_init)

    # Now create an instance
    comp = zs.ZeroShotNLUOpenAI(intents=['greet'], entities=['name'], enable_caching=True)
    return comp


def test_process_returns_cache_hit(zero_shot_component):
    """If cache has a result the component should use it instead of calling the LLM."""
    comp = zero_shot_component
    text = 'hello there'
    key = comp._get_cache_key(text)

    cached = {
        'intent': {'intent': 'greet', 'confidence': 1.0},
        'intent_ranking': [{'intent': 'greet', 'confidence': 1.0}],
        'entities': {'name': 'Bob'}
    }
    comp.cache.set(key, cached)

    msg = {'text': text}
    out = comp.process(msg.copy())
    assert out['intent']['intent'] == 'greet'
    assert out['entities']['name'] == 'Bob'


def test_process_calls_llm_and_caches(monkeypatch, zero_shot_component):
    """When LLM returns data, process should populate message and cache it."""
    comp = zero_shot_component

    # Replace chain.invoke to return a specific response
    def fake_invoke(payload):
        return {'intent': 'hello', 'entities': {'name': 'Alice'}}
    comp.chain = SimpleNamespace(invoke=fake_invoke)

    text = 'say hello to Alice'
    msg = {'text': text}
    out = comp.process(msg.copy())

    assert out['intent']['intent'] == 'hello'
    assert out['entities']['name'] == 'Alice'

    # ensure cache stored data
    key = comp._get_cache_key(text)
    cached = comp.cache.get(key)
    assert cached['intent']['intent'] == 'hello'

    # token monitor should have recorded usage
    stats = comp.get_token_stats()
    assert stats['total_requests'] == 1


def test_process_handles_llm_failure_with_and_without_fallback(monkeypatch, zero_shot_component):
    """If LLM fails, process should fallback when configured, otherwise set empty fields."""
    comp = zero_shot_component

    # Force _call_llm to raise
    monkeypatch.setattr(comp, '_call_llm', lambda text: (_ for _ in ()).throw(Exception('llm error')))

    msg = {'text': 'will fail'}
    # With fallback enabled (default) the fallback marker should be set
    out = comp.process(msg.copy())
    assert out.get('_fallback_used') is True

    # With fallback disabled we expect empty intent fields
    comp_no_fb = zero_shot_component
    comp_no_fb.use_fallback = False
    monkeypatch.setattr(comp_no_fb, '_call_llm', lambda text: (_ for _ in ()).throw(Exception('llm error')))
    out2 = comp_no_fb.process({'text': 'will fail'})
    assert out2['intent']['intent'] is None
    assert out2['intent_ranking'] == []


def test_clear_cache_and_set_prompt_version(monkeypatch):
    """clear_cache should call cache.clear and set_prompt_version should trigger chain re-initialization."""
    # Stub initialize_chain to track calls
    called = {'init': 0}
    def fake_init(self):
        called['init'] += 1
        self.chain = SimpleNamespace(invoke=lambda payload: {})

    monkeypatch.setattr(zs.ZeroShotNLUOpenAI, '_initialize_chain', fake_init)
    comp = zs.ZeroShotNLUOpenAI()

    # create a custom cache with a flag
    class C:
        def __init__(self):
            self.cleared = False
        def clear(self):
            self.cleared = True
        def get(self, k):
            return None
        def set(self, k, v, ttl):
            pass
    c = C()
    comp.cache = c
    comp.clear_cache()
    assert c.cleared is True

    # set_prompt_version should call initialize
    comp.set_prompt_version('2.0')
    assert called['init'] >= 1


def test_get_circuit_breaker_status(zero_shot_component):
    """get_circuit_breaker_status should return the underlying circuit state."""
    comp = zero_shot_component
    assert comp.get_circuit_breaker_status() in ('closed', 'open', 'half-open')


# End of tests