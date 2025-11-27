import asyncio
import time
from datetime import datetime, timedelta
import pytest

import aiohttp

from app.bot.dialogue_manager import http_client
from app.bot.dialogue_manager.http_client import (
    HTTPClient,
    RetryConfig,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    HTTPMetrics,
    APICallException,
    CircuitBreakerException,
)


class FakeResponse:
    def __init__(self, data, status=200, delay=0):
        self._data = data
        self.status = status
        self._delay = delay

    async def json(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, response: FakeResponse):
        self._response = response
        self.closed = False
        self.called = []

    def _make(self, method, url, **kwargs):
        # record call arguments for assertions
        self.called.append((method, url, kwargs))
        return self._response

    def get(self, url, **kwargs):
        return self._make('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self._make('POST', url, **kwargs)

    def put(self, url, **kwargs):
        return self._make('PUT', url, **kwargs)

    def delete(self, url, **kwargs):
        return self._make('DELETE', url, **kwargs)

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Prevent actual sleeping during retries by patching asyncio.sleep."""
    async def _sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, 'sleep', _sleep)
    yield


@pytest.mark.asyncio
async def test_retry_config_get_delay_no_jitter():
    """RetryConfig.get_delay should compute exponential backoff without jitter."""
    rc = RetryConfig(max_retries=3, initial_delay=1.0, exponential_base=2.0, max_delay=10.0, jitter=False)
    assert rc.get_delay(0) == 1.0
    assert rc.get_delay(1) == 2.0
    assert rc.get_delay(2) == 4.0
    assert rc.get_delay(10) == 10.0  # capped by max_delay


def test_http_metrics_basic():
    """HTTPMetrics records requests, computes averages and rates correctly."""
    m = HTTPMetrics()
    assert m.get_average_response_time() == 0.0
    assert m.get_success_rate() == 0.0

    m.record_request(success=True, response_time=0.5, retries=1)
    m.record_request(success=False, response_time=1.5, retries=2)
    assert m.total_requests == 2
    assert m.successful_requests == 1
    assert m.failed_requests == 1
    assert m.total_retries == 3
    assert pytest.approx(m.get_average_response_time(), rel=1e-6) == 1.0
    assert pytest.approx(m.get_success_rate(), rel=1e-6) == 50.0

    m.record_circuit_breaker_trip()
    assert m.circuit_breaker_trips == 1


def test_circuit_breaker_transitions():
    """CircuitBreaker should move between CLOSED, OPEN and HALF_OPEN appropriately."""
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1, success_threshold=1)
    cb = CircuitBreaker(config)
    assert cb.state == CircuitBreakerState.CLOSED

    # Fail twice to open
    cb.record_failure()
    assert cb.state == CircuitBreakerState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN

    # Simulate time passing to allow recovery
    cb.last_failure_time = datetime.now() - timedelta(seconds=2)
    assert cb.can_execute() is True
    assert cb.state == CircuitBreakerState.HALF_OPEN

    # Success should close it (success_threshold == 1)
    cb.record_success()
    assert cb.state == CircuitBreakerState.CLOSED


@pytest.mark.asyncio
async def test_httpclient_success_get(monkeypatch):
    """HTTPClient.call_api should return parsed JSON on successful GET and update metrics."""
    fake_resp = FakeResponse({'result': 'ok'}, status=200)
    fake_session = FakeSession(fake_resp)

    async def fake_get_session(self):
        return fake_session

    monkeypatch.setattr(HTTPClient, '_get_session', fake_get_session)

    client = HTTPClient(retry_config=RetryConfig(max_retries=0, jitter=False))

    result = await client.call_api('http://example.com', 'GET')
    assert result == {'result': 'ok'}
    metrics = client.get_metrics()
    assert metrics.total_requests == 1
    assert metrics.successful_requests == 1
    assert metrics.failed_requests == 0

    await client.close()


@pytest.mark.asyncio
async def test_httpclient_http_error_retries_and_failure(monkeypatch):
    """When server returns 500, HTTPClient should retry and eventually raise APICallException and record metrics."""
    fake_resp = FakeResponse({'error': 'server'}, status=500)
    fake_session = FakeSession(fake_resp)

    async def fake_get_session(self):
        return fake_session

    monkeypatch.setattr(HTTPClient, '_get_session', fake_get_session)

    # small retry count to test flow quickly
    client = HTTPClient(retry_config=RetryConfig(max_retries=2, initial_delay=0.01, jitter=False))

    with pytest.raises(APICallException):
        await client.call_api('http://example.com', 'GET')

    metrics = client.get_metrics()
    assert metrics.total_requests == 1
    assert metrics.successful_requests == 0
    assert metrics.failed_requests == 1
    # retries tracked should reflect attempts-1
    assert metrics.total_retries == 2

    await client.close()


@pytest.mark.asyncio
async def test_httpclient_timeout_behavior(monkeypatch):
    """When request times out, HTTPClient should retry and raise APICallException after retries exhausted."""

    class TimeoutResponse(FakeResponse):
        async def json(self):
            raise asyncio.TimeoutError()

    fake_resp = TimeoutResponse({}, status=200)
    fake_session = FakeSession(fake_resp)

    async def fake_get_session(self):
        return fake_session

    monkeypatch.setattr(HTTPClient, '_get_session', fake_get_session)

    client = HTTPClient(retry_config=RetryConfig(max_retries=1, initial_delay=0.01, jitter=False))

    with pytest.raises(APICallException):
        await client.call_api('http://example.com', 'GET')

    metrics = client.get_metrics()
    assert metrics.failed_requests == 1
    assert metrics.total_retries == 1

    await client.close()


@pytest.mark.asyncio
async def test_call_api_convenience_function(monkeypatch):
    """The module-level call_api should use HTTPClient and close it afterwards."""
    async def fake_client_call_api(self, url, method, headers=None, parameters=None, is_json=False, timeout=None):
        return {'ok': True}

    monkeypatch.setattr(HTTPClient, 'call_api', fake_client_call_api)

    result = await http_client.call_api('http://example.com', 'GET')
    assert result == {'ok': True}


@pytest.mark.asyncio
async def test_unsupported_method_raises_value_error(monkeypatch):
    """Unsupported HTTP method should raise ValueError directly (not treated as client error)."""
    # No need to mock session: the error is raised before network call
    client = HTTPClient()

    with pytest.raises(ValueError):
        await client.call_api('http://example.com', 'PATCH')

    await client.close()


@pytest.mark.asyncio
async def test_circuit_breaker_prevents_execution(monkeypatch):
    """If circuit breaker is open, call_api should raise CircuitBreakerException and metrics should record trips."""
    client = HTTPClient()
    client.circuit_breaker.state = CircuitBreakerState.OPEN
    client.circuit_breaker.last_failure_time = datetime.now()  # recent, so still open

    with pytest.raises(CircuitBreakerException):
        await client.call_api('http://example.com', 'GET')

    assert client.get_metrics().circuit_breaker_trips == 1

    await client.close()