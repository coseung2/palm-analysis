import asyncio
import io
import json

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from palm_backend.config import Settings
from palm_backend.errors import ProviderError
from palm_backend.images import prepare_image
from palm_backend.models import BoothConfig, Observation
from palm_backend.providers import ClaudeAnalyzer, DemoAnalyzer, provider_schema


def image():
    stream = io.BytesIO()
    Image.new("RGB", (320, 320), "white").save(stream, "PNG")
    return prepare_image(stream.getvalue(), "image/png")


def settings():
    return Settings(
        _env_file=None,
        operator_key="test-operator-key-at-least-32-characters",
        analysis_mode="claude",
        anthropic_api_key="fake-key",
    )


def test_real_adapter_request_shape_and_two_stage_separation():
    async def run():
        demo = DemoAnalyzer()
        observation = await demo.observe(image())
        story = await demo.narrate(observation, BoothConfig())
        requests = []

        def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            assert request.url == "https://api.anthropic.com/v1/messages"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert payload["output_config"]["format"]["type"] == "json_schema"
            value = observation if len(requests) == 1 else story
            return httpx.Response(
                200,
                json={
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": value.model_dump_json()}],
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = ClaudeAnalyzer(settings(), client)
            result = await provider.observe(image())
            await provider.narrate(result, BoothConfig())
        assert requests[0]["messages"][0]["content"][0]["type"] == "image"
        assert requests[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"
        assert all(block["type"] == "text" for block in requests[1]["messages"][0]["content"])
        assert "confidence" not in json.dumps(requests[0]["output_config"])

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,payload,code,retryable",
    [
        (429, {}, "provider_busy", True),
        (503, {}, "provider_busy", True),
        (401, {"secret": "do-not-leak"}, "provider_configuration", False),
        (200, {"stop_reason": "refusal"}, "provider_incomplete", True),
        (200, {"stop_reason": "max_tokens"}, "provider_incomplete", True),
        (
            200,
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "bad json"}]},
            "invalid_provider_result",
            True,
        ),
    ],
)
def test_provider_failures_are_safe(status, payload, code, retryable):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(status, json=payload))
        ) as client:
            with pytest.raises(ProviderError) as failure:
                await ClaudeAnalyzer(settings(), client).observe(image())
            assert failure.value.code == code
            assert failure.value.retryable is retryable
            assert "do-not-leak" not in failure.value.message

    asyncio.run(run())


def test_schema_removes_unsupported_constraints_but_local_validation_stays_strict():
    schema = json.dumps(provider_schema(Observation))
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        assert key not in schema
    assert "additionalProperties" in schema
    with pytest.raises(ValidationError):
        Observation(hand="unknown", quality="usable", retake_reason="", lines=[])


def test_normalization_strips_metadata():
    stream = io.BytesIO()
    original = Image.new("RGB", (1600, 1200), "white")
    exif = Image.Exif()
    exif[270] = "private photo metadata"
    original.save(stream, "JPEG", exif=exif)
    normalized = prepare_image(stream.getvalue(), "image/jpeg")
    with Image.open(io.BytesIO(normalized.data)) as cleaned:
        assert max(cleaned.size) == 1600
        assert not cleaned.getexif()
    assert b"private photo metadata" not in normalized.data
