"""Tests for the deliberately small login limiter."""

from radar.auth.rate_limit import LoginRateLimiter


def test_sixth_attempt_is_limited_for_the_same_client() -> None:
    limiter = LoginRateLimiter()

    for attempt in range(5):
        assert limiter.begin_attempt("client", float(attempt)) is None

    assert limiter.begin_attempt("client", 5.0) == 55
    assert limiter.begin_attempt("other-client", 5.0) is None


def test_window_expiration_and_success_clear_attempts() -> None:
    limiter = LoginRateLimiter()

    for attempt in range(5):
        limiter.begin_attempt("client", float(attempt))

    assert limiter.begin_attempt("client", 60.0) is None
    limiter.clear("client")
    assert limiter.begin_attempt("client", 60.0) is None
