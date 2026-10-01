import io
import json
import logging

from app.logging_config import JsonFormatter


def test_json_formatter_includes_extras_and_exceptions() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("test.json")
    log.handlers[:] = [handler]
    log.propagate = False
    log.setLevel(logging.INFO)

    log.info("Handled %s", "message", extra={"receipt_id": "r1", "outcome": "processed"})
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("It failed")

    first, second = (json.loads(line) for line in stream.getvalue().splitlines())
    assert first["message"] == "Handled message"
    assert first["level"] == "INFO" and first["logger"] == "test.json"
    assert (first["receipt_id"], first["outcome"]) == ("r1", "processed")
    assert first["ts"].endswith("+00:00")
    assert second["exc_type"] == "ValueError" and "boom" in second["exc"]
