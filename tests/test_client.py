"""Tests for CortexSTTClient."""

import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.cortex_stt.client import CortexSTTClient
from custom_components.cortex_stt.models import (
    EngineStatus,
    ModelInfo,
    TranscribeResult,
)

BASE_URL = "http://localhost:8769"


@pytest.fixture
def mock_aiohttp():
    with aioresponses() as m:
        yield m


@pytest.fixture
async def client(mock_aiohttp):
    session = aiohttp.ClientSession()
    c = CortexSTTClient(host=BASE_URL, api_key="test-key", session=session)
    yield c
    await session.close()


# ── health ──


async def test_health_success(mock_aiohttp, client):
    """GET /health returns JSON dict."""
    payload = {"status": "ok", "version": "1.2.3"}
    mock_aiohttp.get(f"{BASE_URL}/health", payload=payload)

    result = await client.health()

    assert result == payload


# ── validate ──


async def test_validate_success(mock_aiohttp, client):
    """Validate returns None when health and engine both succeed."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine", payload={"loaded_models": [], "loaded_count": 0}
    )

    result = await client.validate()

    assert result is None


async def test_validate_cannot_connect(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when health raises ClientError."""
    mock_aiohttp.get(f"{BASE_URL}/health", exception=aiohttp.ClientError())

    result = await client.validate()

    assert result == "cannot_connect"


async def test_validate_timeout(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when health raises TimeoutError."""
    mock_aiohttp.get(f"{BASE_URL}/health", exception=TimeoutError())

    result = await client.validate()

    assert result == "cannot_connect"


async def test_validate_invalid_api_key(mock_aiohttp, client):
    """Validate returns 'invalid_api_key' when engine returns 401."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", status=401)

    result = await client.validate()

    assert result == "invalid_api_key"


async def test_validate_invalid_api_key_403(mock_aiohttp, client):
    """Validate returns 'invalid_api_key' when engine returns 403."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", status=403)

    result = await client.validate()

    assert result == "invalid_api_key"


async def test_validate_engine_connection_error(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when engine raises ClientError."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", exception=aiohttp.ClientError())

    result = await client.validate()

    assert result == "cannot_connect"


# ── list_models ──


async def test_list_models(mock_aiohttp, client):
    """GET /api/models parses ModelInfo list with defaults for missing fields."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/models",
        payload=[
            {
                "id": "whisper-large-v3",
                "name": "Whisper Large V3",
                "description": "OpenAI Whisper",
                "engine_type": "whisper",
                "status": "ready",
                "size_mb": 3000,
                "supported_languages": ["en", "zh"],
                "is_loaded": True,
                "is_recommended": True,
            },
            {
                "id": "parakeet-tiny",
                "name": "Parakeet Tiny",
                # Missing optional fields -- should use defaults
            },
        ],
    )

    models = await client.list_models()

    assert len(models) == 2

    m0 = models[0]
    assert isinstance(m0, ModelInfo)
    assert m0.id == "whisper-large-v3"
    assert m0.name == "Whisper Large V3"
    assert m0.description == "OpenAI Whisper"
    assert m0.engine_type == "whisper"
    assert m0.status == "ready"
    assert m0.size_mb == 3000
    assert m0.supported_languages == ["en", "zh"]
    assert m0.is_loaded is True
    assert m0.is_recommended is True

    m1 = models[1]
    assert m1.id == "parakeet-tiny"
    assert m1.name == "Parakeet Tiny"
    assert m1.description == ""
    assert m1.engine_type == ""
    assert m1.status == "unknown"
    assert m1.size_mb == 0
    assert m1.supported_languages == []
    assert m1.is_loaded is False
    assert m1.is_recommended is False


# ── engine_status ──


async def test_engine_status(mock_aiohttp, client):
    """GET /api/engine parses EngineStatus."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine",
        payload={"loaded_models": ["whisper-large-v3"], "loaded_count": 1},
    )

    status = await client.engine_status()

    assert isinstance(status, EngineStatus)
    assert status.loaded_models == ["whisper-large-v3"]
    assert status.loaded_count == 1


# ── transcribe ──


async def test_transcribe_success(mock_aiohttp, client):
    """POST /api/transcribe parses TranscribeResult."""
    mock_aiohttp.post(
        re.compile(r"^http://localhost:8769/api/transcribe"),
        payload={
            "text": "hello world",
            "model": "whisper-large-v3",
            "duration_ms": 1500,
            "inference_ms": 200,
            "segments": [{"start": 0, "end": 1.5, "text": "hello world"}],
        },
    )

    result = await client.transcribe(
        audio_data=b"\x00" * 100,
        model_id="whisper-large-v3",
        language="en",
    )

    assert isinstance(result, TranscribeResult)
    assert result.text == "hello world"
    assert result.model == "whisper-large-v3"
    assert result.duration_ms == 1500
    assert result.inference_ms == 200
    assert len(result.segments) == 1


async def test_transcribe_with_correct_params(mock_aiohttp, client):
    """POST /api/transcribe sends model, language, sample_rate, channels as query params."""
    mock_aiohttp.post(
        re.compile(r"^http://localhost:8769/api/transcribe"),
        payload={
            "text": "test",
            "model": "parakeet",
            "duration_ms": 0,
            "inference_ms": 0,
            "segments": [],
        },
    )

    await client.transcribe(
        audio_data=b"\x00" * 10,
        model_id="parakeet",
        language="zh",
    )

    # aioresponses records calls -- inspect the last request
    history = mock_aiohttp.requests
    # Find the POST to /api/transcribe
    post_calls = [
        (key, calls)
        for key, calls in history.items()
        if key[0] == "POST" and "/api/transcribe" in str(key[1])
    ]
    assert len(post_calls) == 1
    url = post_calls[0][0][1]
    query = url.query

    assert query["model"] == "parakeet"
    assert query["language"] == "zh"
    assert query["sample_rate"] == "16000"
    assert query["channels"] == "1"


# ── headers ──


async def test_headers_contain_bearer_token(mock_aiohttp, client):
    """Authenticated requests include Authorization: Bearer <api_key>."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine",
        payload={"loaded_models": [], "loaded_count": 0},
    )

    await client.engine_status()

    # Inspect the request that was made
    history = mock_aiohttp.requests
    get_calls = [
        (key, calls)
        for key, calls in history.items()
        if key[0] == "GET" and "/api/engine" in str(key[1])
    ]
    assert len(get_calls) == 1
    request_kwargs = get_calls[0][1][0].kwargs
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-key"
