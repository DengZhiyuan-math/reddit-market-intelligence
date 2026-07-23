import pytest

from app.reddit.rate_limiter import (
    RetryPolicy,
    parse_rate_limit_headers,
    should_stop_for_rate_limit,
)


class TemporaryServerError(RuntimeError):
    status_code = 503


def test_parse_rate_limit_headers_normalizes_reddit_headers() -> None:
    snapshot = parse_rate_limit_headers(
        {
            "X-Ratelimit-Used": "12",
            "X-Ratelimit-Remaining": "88.5",
            "X-Ratelimit-Reset": "42",
        }
    )

    assert snapshot.used == 12.0
    assert snapshot.remaining == 88.5
    assert snapshot.reset == 42.0


def test_parse_rate_limit_headers_handles_missing_or_bad_values() -> None:
    snapshot = parse_rate_limit_headers({"X-Ratelimit-Remaining": "unknown"})

    assert snapshot.used is None
    assert snapshot.remaining is None
    assert snapshot.reset is None


def test_should_stop_for_rate_limit_when_remaining_is_at_threshold() -> None:
    snapshot = parse_rate_limit_headers({"X-Ratelimit-Remaining": "5"})

    assert should_stop_for_rate_limit(snapshot, min_remaining=5.0) is True


def test_should_not_stop_when_rate_limit_header_missing() -> None:
    snapshot = parse_rate_limit_headers({})

    assert should_stop_for_rate_limit(snapshot, min_remaining=5.0) is False


def test_retry_policy_retries_transient_errors_with_cap() -> None:
    attempts = 0
    sleeps: list[float] = []

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TemporaryServerError("server error")
        return "ok"

    result = RetryPolicy(max_attempts=3, backoff_seconds=2).run(operation, sleep=sleeps.append)

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [2, 4]


def test_retry_policy_raises_after_max_attempts() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise TemporaryServerError("server error")

    with pytest.raises(TemporaryServerError):
        RetryPolicy(max_attempts=2).run(operation, sleep=lambda seconds: None)

    assert attempts == 2


def test_retry_policy_does_not_retry_permanent_errors() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=3).run(operation)

    assert attempts == 1
