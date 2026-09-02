"""Prompt-injection controls for untrusted Odoo and document content.

Business records, Chatter notes, attachments, and research are data—not
instructions.  This module keeps that boundary enforceable before any model is
called and never includes raw suspicious material in an audit record or log.
"""

import asyncio
from base64 import b64decode
from dataclasses import dataclass
from enum import StrEnum
import hashlib
from html import unescape
import re
import unicodedata
from typing import Protocol, Sequence

from src.chatter_ai.schemas import ChatterAIStartRequest, ContextUnit
from src.core.config import Settings
from src.core.model_profiles import ModelResponsibility, build_model_profiles


class SecurityDecision(StrEnum):
    ALLOWED = "allowed"
    REMOVED = "removed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SecurityEvent:
    source_id: str
    subject_kind: str
    decision: SecurityDecision
    rule_ids: tuple[str, ...]
    content_hash: str
    scanner_provider: str | None = None
    scanner_model: str | None = None
    scanner_verdict: str | None = None


class PromptSecurityRejected(ValueError):
    """The current user request contains unsafe instructions."""

    def __init__(self, events: Sequence[SecurityEvent]) -> None:
        super().__init__("unsafe_ai_instructions")
        self.events = tuple(events)


class PromptInjectionScanner(Protocol):
    """Return True for injection, False for safe, and None if unavailable."""

    provider: str
    model: str

    async def scan(self, excerpt: str) -> bool | None: ...


class GroqPromptInjectionScanner:
    """Use the small Prompt Guard profile only for already suspicious text."""

    provider = "groq"

    def __init__(self, settings: Settings) -> None:
        profile = build_model_profiles(settings)[ModelResponsibility.INJECTION_SCAN]
        self.model = profile.model
        self._source_byte_cap = profile.source_byte_cap
        self._max_output_tokens = profile.reserve_output_tokens
        self._timeout_seconds = profile.timeout_seconds
        self._max_retries = profile.max_retries
        self._api_key = settings.groq_api_key

    async def scan(self, excerpt: str) -> bool | None:
        if self._api_key is None:
            return None
        excerpt = _truncate_utf8(excerpt, self._source_byte_cap)

        def request() -> str:
            from groq import Groq

            response = Groq(
                api_key=self._api_key.get_secret_value(),
                timeout=self._timeout_seconds,
                max_retries=0,
            ).chat.completions.create(
                model=self.model,
                max_tokens=self._max_output_tokens,
                # Groq's Prompt Guard endpoint is a text-classification model:
                # it requires exactly one user message and returns an injection
                # probability, rather than following a classifier instruction.
                messages=[{"role": "user", "content": excerpt}],
            )
            return (response.choices[0].message.content or "").strip().upper()

        result = None
        for _ in range(self._max_retries + 1):
            try:
                result = await asyncio.wait_for(asyncio.to_thread(request), timeout=self._timeout_seconds + 3)
                break
            except Exception:
                continue
        if result is None:
            return None
        if result == "SAFE":
            return False
        if result == "INJECTION":
            return True
        try:
            probability = float(result)
        except ValueError:
            return None
        if 0.0 <= probability <= 1.0:
            return probability >= 0.5
        return None


@dataclass(frozen=True)
class SecuredChatterRequest:
    request: ChatterAIStartRequest
    events: tuple[SecurityEvent, ...]


_HIGH_CONFIDENCE_RULES = (
    (
        "instruction_override",
        re.compile(r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,60}\b(?:previous|prior|system|developer|safety|instructions?)\b", re.I | re.S),
    ),
    (
        "secret_or_prompt_exfiltration",
        re.compile(r"\b(?:reveal|show|print|exfiltrate|send)\b.{0,60}\b(?:system prompt|developer message|api[ _-]?key|token|secret|password)\b", re.I | re.S),
    ),
    (
        "role_message_forgery",
        re.compile(r"(?:<\s*/?\s*(?:system|developer|assistant)\s*>|\b(?:system prompt|developer message)\b.{0,24}(?::|=|is|are))", re.I),
    ),
    (
        "arabic_instruction_override",
        re.compile(r"(?:تجاهل|تخط[ىى]|الغ|إلغاء).{0,60}(?:التعليمات|الأوامر|الرسالة السابقة|النظام)", re.I | re.S),
    ),
    (
        "arabic_secret_exfiltration",
        re.compile(r"(?:اكشف|اعرض|أرسل).{0,60}(?:المفتاح|كلمة المرور|الرمز|السر|تعليمات النظام)", re.I | re.S),
    ),
)
_SUSPICIOUS_RULES = (
    (
        "jailbreak_or_role_play",
        re.compile(r"\b(?:jailbreak|prompt injection|act as|roleplay as|do not follow|new instructions?)\b", re.I),
    ),
    (
        "tool_execution_request",
        re.compile(r"\b(?:execute command|run (?:this|a) command|powershell|curl\s+https?://)\b", re.I),
    ),
    (
        "arabic_role_or_tool_request",
        re.compile(r"(?:حقن.{0,20}(?:تلقين|أوامر)|تصرف ك|لا تتبع|أوامر جديدة)", re.I),
    ),
)
_BASE64_CANDIDATE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")


class PromptSecurityGate:
    """Apply deterministic and model-assisted controls to untrusted text."""

    def __init__(self, scanner: PromptInjectionScanner | None = None) -> None:
        self._scanner = scanner

    async def secure_chatter(self, request: ChatterAIStartRequest) -> SecuredChatterRequest:
        events: list[SecurityEvent] = []
        user_decision = await self._inspect(request.user_message, "user-message", "user_message")
        if user_decision is not None:
            events.append(user_decision)
            if user_decision.decision != SecurityDecision.ALLOWED:
                raise PromptSecurityRejected(events)

        safe_context: list[ContextUnit] = []
        for unit in request.context:
            rendered_source = "\n".join((unit.source_id, unit.kind, unit.title, unit.text))
            event = await self._inspect(rendered_source, unit.source_id, unit.kind)
            if event is None or event.decision == SecurityDecision.ALLOWED:
                safe_context.append(unit)
                if event is not None:
                    events.append(event)
                continue
            events.append(event)
            # Preserve a revision for the source so a dangerous historical note
            # cannot remain retrievable from a previous Neon session revision.
            safe_context.append(unit.model_copy(update={
                "text": "",
                "metadata": {**unit.metadata, "deleted": True, "security_removed": True},
            }))
        return SecuredChatterRequest(
            request=request.model_copy(update={"context": safe_context}),
            events=tuple(events),
        )

    async def filter_model_sources(self, sources: Sequence[object]) -> list[object]:
        """Exclude injected source artifacts before generic document generation."""
        retained: list[object] = []
        for source in sources:
            event = await self._inspect(
                "\n".join((
                    str(getattr(source, "source_id", "")),
                    str(getattr(source, "name", "")),
                    str(getattr(source, "text", "")),
                )),
                str(getattr(source, "source_id", "unknown")),
                str(getattr(source, "type", "source")),
            )
            if event is None or event.decision == SecurityDecision.ALLOWED:
                retained.append(source)
        if not retained:
            raise PromptSecurityRejected(())
        return retained

    async def require_safe_text(self, text: str, source_id: str, subject_kind: str) -> str:
        """Reject a standalone prompt field if it contains unsafe instructions."""
        event = await self._inspect(text, source_id, subject_kind)
        if event is not None and event.decision != SecurityDecision.ALLOWED:
            raise PromptSecurityRejected((event,))
        return text

    async def _inspect(self, text: str, source_id: str, subject_kind: str) -> SecurityEvent | None:
        if not text.strip():
            return None
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        normalized_candidates = _normalized_candidates(text)
        high_rules = _matching_rule_ids(normalized_candidates, _HIGH_CONFIDENCE_RULES)
        if high_rules:
            return SecurityEvent(source_id, subject_kind, SecurityDecision.BLOCKED, high_rules, content_hash, scanner_verdict="deterministic_block")
        suspicious_rules = _matching_rule_ids(normalized_candidates, _SUSPICIOUS_RULES)
        if not suspicious_rules:
            return None
        verdict = await self._scan(_excerpt(text))
        if verdict is False:
            return SecurityEvent(
                source_id, subject_kind, SecurityDecision.ALLOWED, suspicious_rules, content_hash,
                scanner_provider=getattr(self._scanner, "provider", None),
                scanner_model=getattr(self._scanner, "model", None), scanner_verdict="safe",
            )
        return SecurityEvent(
            source_id, subject_kind, SecurityDecision.BLOCKED, suspicious_rules, content_hash,
            scanner_provider=getattr(self._scanner, "provider", None),
            scanner_model=getattr(self._scanner, "model", None),
            scanner_verdict="injection" if verdict else "scanner_unavailable",
        )

    async def _scan(self, excerpt: str) -> bool | None:
        if self._scanner is None:
            return None
        return await self._scanner.scan(excerpt)


def _matching_rule_ids(candidates: Sequence[str], rules: Sequence[tuple[str, re.Pattern[str]]]) -> tuple[str, ...]:
    return tuple(rule_id for rule_id, pattern in rules if any(pattern.search(candidate) for candidate in candidates))


def _normalized_candidates(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", unescape(text))
    normalized = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", normalized)
    candidates = [normalized]
    for match in _BASE64_CANDIDATE.finditer(normalized):
        try:
            decoded = b64decode(match.group(), validate=True).decode("utf-8")
        except Exception:
            continue
        if decoded and sum(character.isprintable() or character.isspace() for character in decoded) / len(decoded) >= 0.9:
            candidates.append(unicodedata.normalize("NFKC", decoded))
    return tuple(candidates)


def _excerpt(text: str) -> str:
    return _truncate_utf8(text, 1_000)


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
