import asyncio

import pytest

from src.core.config import Settings
from src.core.exceptions import QuestionnaireProviderRequestRejected, QuestionnaireProviderUnavailable
from src.core.model_profiles import (
    ModelResponsibility,
    build_compound_fallback_profile,
    build_model_profiles,
)
from src.shared.llm.contracts import GeneratedText
from src.shared.llm.router import ModelRouter


class QuotaGuardStub:
    def __init__(self) -> None:
        self.reservations: list[tuple[object, int]] = []

    async def acquire(self, profile, input_tokens: int) -> None:
        self.reservations.append((profile, input_tokens))


class GeneratorStub:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> GeneratedText:
        self.prompts.append(prompt)
        return GeneratedText(prompt, "test", "test-model", 3, 2)


class UnavailableGenerator:
    async def generate(self, _: str) -> GeneratedText:
        raise QuestionnaireProviderUnavailable("primary unavailable")


class PayloadRejectingGenerator:
    async def generate(self, _: str) -> GeneratedText:
        raise QuestionnaireProviderRequestRejected("payload too large")


def _router(settings: Settings) -> tuple[ModelRouter, GeneratorStub]:
    generator = GeneratorStub()
    profiles = build_model_profiles(settings)
    router = ModelRouter(
        profiles,
        {ModelResponsibility.ENGLISH_GENERATION: generator},
    )
    return router, generator


def test_router_uses_only_the_assigned_model_responsibility() -> None:
    router, generator = _router(Settings())

    result = asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "Create an SOW."))

    assert result.provider == "test"
    assert generator.prompts == ["Create an SOW."]


def test_router_reserves_durable_quota_before_the_provider_call() -> None:
    settings = Settings()
    generator = GeneratorStub()
    guard = QuotaGuardStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.ENGLISH_GENERATION: generator},
        quota_guard=guard,
    )

    asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "Create an SOW."))

    assert len(guard.reservations) == 1
    assert guard.reservations[0][0].responsibility == ModelResponsibility.ENGLISH_GENERATION
    assert guard.reservations[0][1] > 0


def test_router_rejects_an_oversized_request_before_provider_call() -> None:
    router, generator = _router(Settings(ai_generation_source_bytes=256))

    with pytest.raises(QuestionnaireProviderUnavailable, match="source-byte budget"):
        asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "x" * 257))

    assert generator.prompts == []


def test_router_rejects_a_disabled_or_unmeasured_profile() -> None:
    router, _ = _router(Settings(
        ai_generation_enabled=False,
    ))

    with pytest.raises(QuestionnaireProviderUnavailable, match="not enabled"):
        asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "test"))


def test_router_uses_compound_only_after_the_primary_is_unavailable() -> None:
    settings = Settings()
    fallback = GeneratorStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.ENGLISH_GENERATION: UnavailableGenerator()},
        {ModelResponsibility.ENGLISH_GENERATION: build_compound_fallback_profile(settings, ModelResponsibility.ENGLISH_GENERATION)},
        {ModelResponsibility.ENGLISH_GENERATION: fallback},
    )

    result = asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "Create an SOW."))

    assert result.provider == "test"
    assert fallback.prompts == ["Create an SOW."]


def test_router_compacts_an_oversized_fallback_before_calling_it() -> None:
    settings = Settings(ai_generation_fallback_source_bytes=256)
    fallback = GeneratorStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.ENGLISH_GENERATION: UnavailableGenerator()},
        {ModelResponsibility.ENGLISH_GENERATION: build_compound_fallback_profile(settings, ModelResponsibility.ENGLISH_GENERATION)},
        {ModelResponsibility.ENGLISH_GENERATION: fallback},
    )

    asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "x" * 257))

    assert len(fallback.prompts) == 1
    assert len(fallback.prompts[0].encode("utf-8")) <= 256
    assert "Context compacted" in fallback.prompts[0]


def test_router_compacts_a_provider_rejected_payload_for_compound() -> None:
    settings = Settings(ai_generation_fallback_source_bytes=1000)
    fallback = GeneratorStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.ENGLISH_GENERATION: PayloadRejectingGenerator()},
        {ModelResponsibility.ENGLISH_GENERATION: build_compound_fallback_profile(settings, ModelResponsibility.ENGLISH_GENERATION)},
        {ModelResponsibility.ENGLISH_GENERATION: fallback},
    )

    asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, "x" * 1200))

    assert len(fallback.prompts[0].encode("utf-8")) < 1000
    assert "Context compacted" in fallback.prompts[0]


def test_router_compacts_a_locally_oversized_primary_request_for_compound() -> None:
    settings = Settings(
        ai_generation_source_bytes=256,
        ai_generation_fallback_source_bytes=1000,
    )
    fallback = GeneratorStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.ENGLISH_GENERATION: GeneratorStub()},
        {ModelResponsibility.ENGLISH_GENERATION: build_compound_fallback_profile(
            settings, ModelResponsibility.ENGLISH_GENERATION,
        )},
        {ModelResponsibility.ENGLISH_GENERATION: fallback},
    )

    prompt = "x" * 300
    asyncio.run(router.generate(ModelResponsibility.ENGLISH_GENERATION, prompt))

    assert len(fallback.prompts) == 1
    fallback_bytes = len(fallback.prompts[0].encode("utf-8"))
    assert fallback_bytes < 1_000
    assert fallback_bytes < len(prompt.encode("utf-8"))
    assert "Context compacted" in fallback.prompts[0]


def test_router_compacts_rate_limited_primary_for_smaller_fallback_budget() -> None:
    settings = Settings(
        ai_review_source_bytes=1_000,
        ai_review_fallback_source_bytes=256,
    )
    fallback = GeneratorStub()
    router = ModelRouter(
        build_model_profiles(settings),
        {ModelResponsibility.STRUCTURED_REVIEW: UnavailableGenerator()},
        {ModelResponsibility.STRUCTURED_REVIEW: build_compound_fallback_profile(
            settings, ModelResponsibility.STRUCTURED_REVIEW,
        )},
        {ModelResponsibility.STRUCTURED_REVIEW: fallback},
    )
    prompt = "x" * 300

    asyncio.run(router.generate(ModelResponsibility.STRUCTURED_REVIEW, prompt))

    assert len(fallback.prompts) == 1
    assert len(fallback.prompts[0].encode("utf-8")) <= 256
    assert "Context compacted" in fallback.prompts[0]
