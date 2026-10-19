from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.test, https://b.test/ ,")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_origins == ["http://a.test", "https://b.test"]


def test_wildcard_origin_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            _env_file=None, environment="production", allowed_origins=["*"]
        )
