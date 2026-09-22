from __future__ import annotations

from datetime import UTC, datetime

from app.modules.auth.service import CHALLENGE_TTL, RegistrationResult


def test_registration_result_is_generic() -> None:
    assert RegistrationResult() == RegistrationResult(accepted=True)
    assert "existing" not in repr(RegistrationResult()).lower()


def test_verification_challenge_window_is_sixty_minutes() -> None:
    issued = datetime(2026, 1, 1, tzinfo=UTC)

    assert CHALLENGE_TTL.total_seconds() == 60 * 60
    assert issued + CHALLENGE_TTL > issued
