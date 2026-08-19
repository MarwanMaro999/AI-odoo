"""Temporary local run storage for questionnaire development and tests."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from uuid import UUID, uuid4

from src.core.exceptions import QuestionnaireRequestConflict, QuestionnaireRunNotFound
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.schemas.response import (
    QuestionnaireRunState,
    QuestionnaireStatusResponse,
)


@dataclass
class StoredQuestionnaireRun:
    """Internal temporary representation of one submitted questionnaire run."""

    questionnaire_run_id: UUID
    idempotency_key: str
    request_fingerprint: str
    questionnaire_identifier: str
    questionnaire_version: str
    state: QuestionnaireRunState
    submitted_at: datetime

    def to_status_response(self) -> QuestionnaireStatusResponse:
        """Create the safe status response returned by the controller."""
        return QuestionnaireStatusResponse(
            questionnaire_run_id=self.questionnaire_run_id,
            state=self.state,
            questionnaire_identifier=self.questionnaire_identifier,
            questionnaire_version=self.questionnaire_version,
            submitted_at=self.submitted_at,
        )


class InMemoryQuestionnaireRunRepository:
    """Development-only storage; replace with an Odoo-backed repository later."""

    def __init__(self) -> None:
        self._runs_by_id: dict[UUID, StoredQuestionnaireRun] = {}
        self._runs_by_idempotency_key: dict[str, StoredQuestionnaireRun] = {}
        self._lock = RLock()

    def create_or_get(
        self,
        request: StartQuestionnaireRequest,
        questionnaire_version: str,
    ) -> tuple[StoredQuestionnaireRun, bool]:
        """Create a queued run once, or return an identical previous submission."""
        fingerprint = self._create_request_fingerprint(request)
        with self._lock:
            existing = self._runs_by_idempotency_key.get(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise QuestionnaireRequestConflict()
                return existing, False

            run = StoredQuestionnaireRun(
                questionnaire_run_id=uuid4(),
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                questionnaire_identifier=request.questionnaire_identifier,
                questionnaire_version=questionnaire_version,
                state=QuestionnaireRunState.QUEUED,
                submitted_at=datetime.now(timezone.utc),
            )
            self._runs_by_id[run.questionnaire_run_id] = run
            self._runs_by_idempotency_key[run.idempotency_key] = run
            return run, True

    def get(self, questionnaire_run_id: UUID) -> StoredQuestionnaireRun:
        """Return a stored questionnaire run or raise a safe not-found error."""
        with self._lock:
            run = self._runs_by_id.get(questionnaire_run_id)
            if run is None:
                raise QuestionnaireRunNotFound()
            return run

    @staticmethod
    def _create_request_fingerprint(request: StartQuestionnaireRequest) -> str:
        """Make a stable hash to detect idempotency-key reuse with different data."""
        serialised_request = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialised_request.encode("utf-8")).hexdigest()
