from pathlib import Path

from rbvecchi.db import Database


def test_transitions_and_stats(tmp_path: Path) -> None:
    db = Database(tmp_path / "garage.db")

    initial = db.reconcile(False, 1000.0)
    assert initial is not None
    assert initial.kind == "INITIAL"

    opened = db.reconcile(True, 1100.0)
    assert opened is not None
    assert opened.kind == "OPEN"

    assert db.reconcile(True, 1130.0) is None

    closed = db.reconcile(False, 1165.0)
    assert closed is not None
    assert closed.kind == "CLOSE"
    assert closed.duration_seconds == 65

    events = db.list_events(10)
    assert [event["event_type"] for event in events] == ["CLOSE", "OPEN", "INITIAL"]

    stats = db.stats_between(1000.0, 1200.0)
    assert stats == {"openings": 1, "open_seconds": 65}

    state = db.get_current_state()
    assert state["garage_open"] is False
