from __future__ import annotations

from app.modules.auth.service import VerificationResult


def test_verification_result_is_explicit_and_safe() -> None:
    assert VerificationResult(verified=True).verified is True
    assert VerificationResult(verified=False).verified is False
