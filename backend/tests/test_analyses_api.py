"""Conversations and analysis runs through the HTTP API, with a scripted model.

Covers the full flow (upload -> conversation -> question -> real computation -> chart ->
grounded answer -> follow-up -> history), ownership, conversation isolation, failures,
cancellation and restart recovery.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMTimeoutError
from app.agent.llm.fake import FakeProvider
from app.db.models import AnalysisEvent, AnalysisRun, Conversation
from app.main import create_app
from tests.conftest import CSRF_HEADERS, make_settings, new_client, register
from tests.factories import SAMPLE_SALES
from tests.scripted import QUESTION, HoldingExecutor, InlineExecutor, sales_provider


class ProviderSpy:
    """Hands out scripted providers and remembers them, to inspect what the model saw."""

    def __init__(self, factory: Any = sales_provider) -> None:
        self.factory = factory
        self.providers: list[FakeProvider] = []

    def __call__(self) -> FakeProvider:
        provider = self.factory()
        self.providers.append(provider)
        return provider

    def plan_prompt(self, index: int = -1) -> str:
        return self.providers[index].calls[0].messages[0].text  # type: ignore[union-attr]


@pytest.fixture
def spy() -> ProviderSpy:
    return ProviderSpy()


@pytest.fixture
def analysis_app(db_engine: Engine, tmp_path: Path, spy: ProviderSpy) -> FastAPI:
    return create_app(make_settings(tmp_path), provider_factory=spy, run_executor=InlineExecutor())


@pytest.fixture
def client(analysis_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(analysis_app, raise_server_exceptions=False, headers=CSRF_HEADERS) as c:
        yield c


def upload_sales(client: TestClient) -> str:
    response = client.post(
        "/api/datasets", files={"file": ("sales.csv", SAMPLE_SALES.read_bytes(), "text/csv")}
    )
    assert response.status_code == 201, response.text
    dataset_id: str = response.json()["id"]
    return dataset_id


def new_conversation(client: TestClient, dataset_id: str) -> str:
    response = client.post("/api/conversations", json={"dataset_id": dataset_id})
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["id"]
    return conversation_id


def ask(client: TestClient, conversation_id: str, question: str = QUESTION) -> dict[str, Any]:
    response = client.post(
        f"/api/conversations/{conversation_id}/analyses", json={"question": question}
    )
    assert response.status_code == 202, response.text
    run: dict[str, Any] = response.json()
    return run


def test_full_analysis_flow(client: TestClient, spy: ProviderSpy) -> None:
    register(client)
    dataset_id = upload_sales(client)
    conversation_id = new_conversation(client, dataset_id)

    queued = ask(client, conversation_id)
    detail = client.get(f"/api/analyses/{queued['id']}").json()
    assert detail["status"] == "completed", detail
    assert detail["stop_reason"] == "completed"
    assert detail["model"] == "scripted-test"

    # Activity events are ordered and reflect operations that actually ran.
    labels = [e["label"] for e in detail["events"]]
    assert labels[0] == "Inspecting dataset"
    assert labels[1] == "Planning analysis"
    assert any(label.startswith("Comparing periods: Sum of Revenue") for label in labels)
    assert any(label.startswith("Generating chart") for label in labels)
    assert labels[-2:] == ["Preparing answer", "Validating results"]
    assert [e["seq"] for e in detail["events"]] == sorted(e["seq"] for e in detail["events"])
    assert all(e["status"] == "completed" for e in detail["events"])

    outcome = detail["outcome"]
    result = outcome["results"][0]
    assert result["operation"] == "period_comparison"
    # The computed numbers match an independent pandas calculation.
    truth = pd.read_csv(SAMPLE_SALES, parse_dates=["Order Date"])
    q2 = truth[truth["Order Date"].between("2024-04-01", "2024-06-30")]["Revenue"].sum()
    q3 = truth[truth["Order Date"].between("2024-07-01", "2024-09-30")]["Revenue"].sum()
    assert result["summary"]["baseline_total"] == pytest.approx(q2)
    assert result["summary"]["current_total"] == pytest.approx(q3)
    # The chart is built from that result.
    chart = outcome["charts"][0]
    assert chart["source_result_id"] == result["id"]
    assert chart["traces"][0]["y"] == [row[3] for row in result["table"]["rows"]]
    # The answer is grounded and names the planted cause.
    assert outcome["grounding"]["unverified_numbers"] == []
    assert outcome["grounding"]["checked_numbers"] >= 4
    assert "West" in outcome["answer"]["summary"]
    assert outcome["answer"]["chart_ids"] == ["c1"]
    assert detail["answer_summary"] == outcome["answer"]["summary"]

    conversation = client.get(f"/api/conversations/{conversation_id}").json()
    assert conversation["title"] == QUESTION
    assert [r["id"] for r in conversation["runs"]] == [queued["id"]]
    assert conversation["run_count"] == 1


def test_follow_up_uses_earlier_turns_of_the_same_conversation_only(
    client: TestClient, spy: ProviderSpy
) -> None:
    register(client)
    dataset_id = upload_sales(client)
    first = new_conversation(client, dataset_id)
    ask(client, first)
    ask(client, first, "Which region contributed most to the decline?")
    follow_up_prompt = spy.plan_prompt()
    assert QUESTION in follow_up_prompt
    assert "contributed most of the decline" in follow_up_prompt  # earlier answer summary

    other = new_conversation(client, dataset_id)
    ask(client, other, "Show me the trend.")
    assert QUESTION not in spy.plan_prompt()
    assert "first question in the conversation" in spy.plan_prompt()

    runs = client.get(f"/api/conversations/{first}").json()["runs"]
    assert [r["question"] for r in runs] == [
        QUESTION,
        "Which region contributed most to the decline?",
    ]


def test_users_cannot_reach_each_others_conversations_or_analyses(client: TestClient) -> None:
    register(client, email="owner@example.com")
    dataset_id = upload_sales(client)
    conversation_id = new_conversation(client, dataset_id)
    run_id = ask(client, conversation_id)["id"]

    intruder = new_client(client.app)
    register(intruder, email="intruder@example.com")
    checks = [
        intruder.get(f"/api/conversations/{conversation_id}"),
        intruder.patch(f"/api/conversations/{conversation_id}", json={"title": "mine"}),
        intruder.delete(f"/api/conversations/{conversation_id}"),
        intruder.post(f"/api/conversations/{conversation_id}/analyses", json={"question": "steal"}),
        intruder.get(f"/api/analyses/{run_id}"),
        intruder.post(f"/api/analyses/{run_id}/cancel"),
        intruder.post("/api/conversations", json={"dataset_id": dataset_id}),
    ]
    assert [r.status_code for r in checks] == [404] * len(checks)
    assert intruder.get("/api/conversations").json()["total"] == 0
    assert intruder.get("/api/analyses").json()["total"] == 0
    # Filtering by someone else's ids reveals nothing either.
    assert intruder.get("/api/analyses", params={"dataset_id": dataset_id}).json()["total"] == 0
    # The owner is unaffected.
    assert client.get(f"/api/analyses/{run_id}").json()["status"] == "completed"


def test_analysis_requires_a_configured_model(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, anthropic_api_key=None))
    with TestClient(app, headers=CSRF_HEADERS) as c:
        register(c)
        assert c.get("/api/config").json() == {
            "analysis_enabled": False,
            "model": None,
            "max_question_length": 2000,
        }
        conversation_id = new_conversation(c, upload_sales(c))
        response = c.post(
            f"/api/conversations/{conversation_id}/analyses", json={"question": "Hi?"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_not_configured"


def test_one_active_analysis_per_conversation(client: TestClient, db_engine: Engine) -> None:
    register(client)
    conversation_id = new_conversation(client, upload_sales(client))
    run_id = ask(client, conversation_id)["id"]
    with Session(db_engine) as db:
        db.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(status="running"))
        db.commit()
    response = client.post(
        f"/api/conversations/{conversation_id}/analyses", json={"question": "Next?"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "analysis_in_progress"


def test_cancel_queued_analysis(db_engine: Engine, tmp_path: Path) -> None:
    holding = HoldingExecutor()
    app = create_app(make_settings(tmp_path), provider_factory=sales_provider, run_executor=holding)
    with TestClient(app, headers=CSRF_HEADERS) as c:
        register(c)
        conversation_id = new_conversation(c, upload_sales(c))
        run = ask(c, conversation_id)
        assert run["status"] == "queued"
        cancelled = c.post(f"/api/analyses/{run['id']}/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["status"] == "cancelled"
        # If a worker picks it up afterwards, it does nothing.
        fn, args = holding.held[0]
        fn(*args)
        assert c.get(f"/api/analyses/{run['id']}").json()["status"] == "cancelled"


def test_restart_recovery_marks_unfinished_runs_failed(
    client: TestClient, analysis_app: FastAPI, db_engine: Engine
) -> None:
    register(client)
    conversation_id = new_conversation(client, upload_sales(client))
    run_id = ask(client, conversation_id)["id"]
    with Session(db_engine) as db:
        db.execute(update(AnalysisRun).where(AnalysisRun.id == run_id).values(status="running"))
        db.commit()
    assert analysis_app.state.runner.recover_interrupted() == 1
    detail = client.get(f"/api/analyses/{run_id}").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "interrupted"


def test_model_failure_is_stored_safely(db_engine: Engine, tmp_path: Path) -> None:
    def failing() -> FakeProvider:
        provider = sales_provider()
        provider._tool_step = lambda call: LLMTimeoutError(  # type: ignore[assignment]
            "The language model took too long to respond."
        )
        return provider

    app = create_app(
        make_settings(tmp_path), provider_factory=failing, run_executor=InlineExecutor()
    )
    with TestClient(app, headers=CSRF_HEADERS) as c:
        register(c)
        run = ask(c, new_conversation(c, upload_sales(c)))
        detail = c.get(f"/api/analyses/{run['id']}").json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "llm_timeout"
    assert detail["error_message"] == "The language model took too long to respond."
    assert detail["events"][-1]["status"] == "failed"


def test_history_listing_and_filters(client: TestClient) -> None:
    register(client)
    sales = upload_sales(client)
    other = upload_sales(client)
    ask(client, new_conversation(client, sales))
    ask(client, new_conversation(client, other), "Show me the trend.")
    history = client.get("/api/analyses").json()
    assert history["total"] == 2
    assert history["items"][0]["question"] == "Show me the trend."
    assert history["items"][0]["dataset_name"] == "sales"
    filtered = client.get("/api/analyses", params={"dataset_id": sales}).json()
    assert [i["question"] for i in filtered["items"]] == [QUESTION]
    conversations = client.get("/api/conversations", params={"dataset_id": other}).json()
    assert conversations["total"] == 1
    assert conversations["items"][0]["run_count"] == 1


def test_rename_and_delete_cascade(client: TestClient, db_engine: Engine) -> None:
    register(client)
    dataset_id = upload_sales(client)
    conversation_id = new_conversation(client, dataset_id)
    ask(client, conversation_id)
    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Q3 review"})
    assert renamed.json()["title"] == "Q3 review"
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    with Session(db_engine) as db:
        assert db.scalars(select(AnalysisRun)).all() == []
        assert db.scalars(select(AnalysisEvent)).all() == []
    # Deleting a dataset removes its conversations too.
    second = new_conversation(client, dataset_id)
    ask(client, second)
    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    with Session(db_engine) as db:
        assert db.scalars(select(Conversation)).all() == []


@pytest.mark.parametrize("question", ["", "x" * 2001])
def test_question_validation(client: TestClient, question: str) -> None:
    register(client)
    conversation_id = new_conversation(client, upload_sales(client))
    response = client.post(
        f"/api/conversations/{conversation_id}/analyses", json={"question": question}
    )
    assert response.status_code == 422


def test_unknown_ids_return_404(client: TestClient) -> None:
    register(client)
    assert client.get(f"/api/analyses/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/conversations/{uuid.uuid4()}").status_code == 404
    response = client.post("/api/conversations", json={"dataset_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_analysis_rate_limit(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(
        make_settings(tmp_path, analyses_per_user_per_hour=1),
        provider_factory=sales_provider,
        run_executor=InlineExecutor(),
    )
    with TestClient(app, headers=CSRF_HEADERS) as c:
        register(c)
        conversation_id = new_conversation(c, upload_sales(c))
        ask(c, conversation_id)
        response = c.post(
            f"/api/conversations/{conversation_id}/analyses", json={"question": "Again?"}
        )
    assert response.status_code == 429
