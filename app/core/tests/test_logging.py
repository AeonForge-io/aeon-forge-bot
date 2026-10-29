"""Tests for app.core.logging module."""

import json

import pytest

from app.core.logging import (
    get_correlation_id,
    get_logger,
    set_correlation_id,
    setup_logging,
)


def test_setup_logging_configures_structlog() -> None:
    """Test that setup_logging() configures structlog without errors."""
    # Should not raise any exceptions
    setup_logging(log_level="INFO")


def test_get_logger_returns_wrapped_logger() -> None:
    """Test that get_logger() returns a logger with expected methods."""
    setup_logging(log_level="INFO")
    logger = get_logger("test")

    # Verify logger has standard logging methods
    assert hasattr(logger, "info")
    assert hasattr(logger, "error")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "debug")


def test_logger_outputs_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that logger outputs valid JSON with expected fields."""
    setup_logging(log_level="INFO")
    logger = get_logger("test")

    logger.info("test.event.started", user_id=123, action="test")

    captured = capsys.readouterr()
    log_line = captured.out.strip()

    # Parse as JSON
    log_data = json.loads(log_line)

    # Verify expected fields
    assert log_data["event"] == "test.event.started"
    assert log_data["user_id"] == 123
    assert log_data["action"] == "test"
    assert "timestamp" in log_data
    assert "level" in log_data


def test_logger_includes_correlation_id(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that correlation ID is included in log output when set."""
    setup_logging(log_level="INFO")
    logger = get_logger("test")

    # Set correlation ID
    set_correlation_id("test-correlation-123")

    logger.info("test.event.with_correlation")

    captured = capsys.readouterr()
    log_line = captured.out.strip()

    # Parse as JSON
    log_data = json.loads(log_line)

    # Verify correlation ID is present
    assert log_data["correlation_id"] == "test-correlation-123"


def test_correlation_id_get_set() -> None:
    """Test that correlation ID getter and setter work correctly."""
    # Set correlation ID
    set_correlation_id("test-id-456")

    # Get correlation ID
    correlation_id = get_correlation_id()

    assert correlation_id == "test-id-456"


def test_logger_hybrid_dotted_namespace_format(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that logger follows hybrid dotted namespace pattern."""
    setup_logging(log_level="INFO")
    logger = get_logger("app.core.database")

    logger.info("database.pool.created", min_size=2, max_size=5)

    captured = capsys.readouterr()
    log_line = captured.out.strip()

    # Parse as JSON
    log_data = json.loads(log_line)

    # Verify event follows pattern: {domain}.{component}.{action_state}
    assert log_data["event"] == "database.pool.created"
    assert "." in log_data["event"]  # Contains dots for namespace


def test_logger_exception_info(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that exc_info=True includes exception traceback in JSON."""
    setup_logging(log_level="INFO")
    logger = get_logger("test")

    try:
        raise ValueError("Test exception")
    except ValueError:
        logger.error("test.exception.occurred", exc_info=True)

    captured = capsys.readouterr()
    log_line = captured.out.strip()

    # Parse as JSON
    log_data = json.loads(log_line)

    # Verify exception info is present
    assert "exception" in log_data
    assert "ValueError" in log_data["exception"]
    assert "Test exception" in log_data["exception"]
