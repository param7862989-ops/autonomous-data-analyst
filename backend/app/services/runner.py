"""Executes analysis runs in a bounded background thread pool.

The HTTP request that starts an analysis only records it as queued and returns; a worker thread
loads the dataset into a fresh sandboxed engine, runs the agent, and persists activity events
as they happen and the outcome at the end. Clients poll the run.

Trade-off (documented in KNOWN_LIMITATIONS): runs live in the API process, so a restart
interrupts them. On startup, any run left queued or running is marked failed.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.agent.context import DatasetContext
from app.agent.graph import AgentDeps, AgentLimits, AnalysisAgent
from app.agent.llm.base import LLMError, LLMProvider
from app.agent.schemas import ActivityEvent, AgentOutcome
from app.agent.tools import ToolExecutor
from app.analytics.engine import AnalyticsEngine, EngineLimits
from app.config import Settings
from app.datasets.storage import DatasetStorage
from app.db.base import utcnow
from app.db.models import AnalysisEvent, AnalysisRun, Conversation, Dataset
from app.services.conversations import ACTIVE_STATUSES, prior_turns

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], LLMProvider]
_CANCEL_CHECK_INTERVAL = 1.0


class EventRecorder:
    """Persists activity events, upserting by key so a step's status can progress."""

    def __init__(self, session_factory: sessionmaker[Session], run_id: uuid.UUID) -> None:
        self._session_factory = session_factory
        self._run_id = run_id
        self._seq: dict[str, int] = {}

    def __call__(self, event: ActivityEvent) -> None:
        seq = self._seq.setdefault(event.key, len(self._seq) + 1)
        now = utcnow()
        values = {
            "run_id": self._run_id,
            "key": event.key[:64],
            "seq": seq,
            "kind": event.kind,
            "label": event.label[:300],
            "status": event.status,
            "detail": event.detail,
            "result_id": event.result_id,
            "created_at": now,
            "updated_at": now,
        }
        statement = insert(AnalysisEvent).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_analysis_events_run_id_key",
            set_={
                "label": statement.excluded.label,
                "status": statement.excluded.status,
                "detail": statement.excluded.detail,
                "result_id": statement.excluded.result_id,
                "updated_at": statement.excluded.updated_at,
            },
        )
        try:
            with self._session_factory() as db:
                db.execute(statement)
                db.commit()
        except Exception:
            logger.exception("Failed to record an activity event")


class CancelChecker:
    """Reads the run's cancel flag, at most once per interval."""

    def __init__(self, session_factory: sessionmaker[Session], run_id: uuid.UUID) -> None:
        self._session_factory = session_factory
        self._run_id = run_id
        self._checked_at = 0.0
        self._cancelled = False

    def __call__(self) -> bool:
        if self._cancelled:
            return True
        now = time.monotonic()
        if now - self._checked_at < _CANCEL_CHECK_INTERVAL:
            return False
        self._checked_at = now
        with self._session_factory() as db:
            row = db.execute(
                select(AnalysisRun.cancel_requested).where(AnalysisRun.id == self._run_id)
            ).first()
        # A run whose row disappeared (conversation or dataset deleted) is cancelled too.
        self._cancelled = row is None or bool(row[0])
        return self._cancelled


class AnalysisRunner:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        settings: Settings,
        storage: DatasetStorage,
        provider_factory: ProviderFactory,
        executor: Executor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._storage = storage
        self._provider_factory = provider_factory
        self._executor = executor or ThreadPoolExecutor(
            max_workers=settings.analysis_workers, thread_name_prefix="analysis"
        )
        self._futures: set[Future[None]] = set()
        self._lock = threading.Lock()

    def submit(self, run_id: uuid.UUID) -> None:
        future = self._executor.submit(self._execute_safely, run_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget)

    def _forget(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def recover_interrupted(self) -> int:
        """Mark runs left unfinished by a previous process as failed. Returns how many."""
        with self._session_factory() as db:
            result = db.execute(
                update(AnalysisRun)
                .where(AnalysisRun.status.in_(ACTIVE_STATUSES))
                .values(
                    status="failed",
                    stop_reason="error",
                    error_code="interrupted",
                    error_message="The analysis was interrupted by a server restart. Ask again.",
                    finished_at=utcnow(),
                )
            )
            db.commit()
            count = int(getattr(result, "rowcount", 0) or 0)
        if count:
            logger.warning("Marked %d interrupted analysis run(s) as failed", count)
        return count

    # --- Execution ---------------------------------------------------------------------------

    def _execute_safely(self, run_id: uuid.UUID) -> None:
        try:
            self._execute(run_id)
        except Exception:
            logger.exception("Analysis run crashed")
            self._finish(
                run_id,
                status="failed",
                stop_reason="error",
                error_code="internal_error",
                error_message="The analysis failed unexpectedly.",
            )

    def _execute(self, run_id: uuid.UUID) -> None:
        with self._session_factory() as db:
            run = db.get(AnalysisRun, run_id)
            if run is None or run.status != "queued":
                return  # deleted or cancelled before it started
            dataset = db.get(Dataset, run.dataset_id)
            if dataset is None:
                return
            run.status = "running"
            run.started_at = utcnow()
            db.commit()
            question = run.question
            history = prior_turns(db, run)
            context = DatasetContext.from_dataset(
                name=dataset.name, columns=dataset.columns, profile=dataset.profile
            )
            profile = dataset.profile
            storage_key = dataset.storage_key

        try:
            provider = self._provider_factory()
        except LLMError as error:
            self._finish(
                run_id,
                status="failed",
                stop_reason="error",
                error_code=error.code,
                error_message=error.message,
            )
            return

        settings = self._settings
        with AnalyticsEngine(
            self._storage.path_for(storage_key), EngineLimits.from_settings(settings)
        ) as engine:
            agent = AnalysisAgent(
                AgentDeps(
                    provider=provider,
                    executor=ToolExecutor(engine=engine, context=context, profile=profile),
                    context=context,
                    history=history,
                    limits=AgentLimits(
                        max_iterations=settings.agent_max_iterations,
                        max_tool_calls=settings.agent_max_tool_calls,
                        max_tool_calls_per_turn=settings.agent_max_tool_calls_per_turn,
                        deadline_seconds=settings.agent_deadline_seconds,
                    ),
                    emit=EventRecorder(self._session_factory, run_id),
                    should_cancel=CancelChecker(self._session_factory, run_id),
                )
            )
            outcome = agent.run(question)
        self._finish(
            run_id,
            status=outcome.status,
            stop_reason=outcome.stop_reason,
            error_code=outcome.error_code,
            error_message=outcome.error_message,
            outcome=outcome,
            model=provider.model_name,
        )

    def _finish(
        self,
        run_id: uuid.UUID,
        *,
        status: str,
        stop_reason: str,
        error_code: str | None = None,
        error_message: str | None = None,
        outcome: AgentOutcome | None = None,
        model: str | None = None,
    ) -> None:
        with self._session_factory() as db:
            run = db.get(AnalysisRun, run_id)
            if run is None:
                logger.info("Analysis run was deleted before it finished")
                return
            run.status = status
            run.stop_reason = stop_reason
            run.error_code = error_code
            run.error_message = error_message
            run.outcome = outcome.model_dump(mode="json") if outcome else None
            run.model = model
            run.finished_at = utcnow()
            conversation = db.get(Conversation, run.conversation_id)
            if conversation is not None:
                conversation.updated_at = utcnow()
            db.commit()
