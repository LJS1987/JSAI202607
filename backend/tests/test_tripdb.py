"""tripdb SQLite 저장소 왕복 검증 (tmp_path 임시 DB)."""

from backend.app import tripdb


def test_log_and_read_pings(tmp_path):
    conn = tripdb.connect(tmp_path / "trips.db")
    tripdb.log_ping(conn, "n1", 12.5, 37.5, 127.0, 5.0, ts=100.0)
    tripdb.log_ping(conn, "n1", 8.0, 37.5, 127.0, 0.0, ts=105.0)
    tripdb.log_ping(conn, "n2", 20.0, 37.6, 127.1, 10.0, ts=110.0)

    n1_pings = tripdb.pings_for_node(conn, "n1")
    assert n1_pings == [(100.0, 5.0), (105.0, 0.0)]

    assert set(tripdb.distinct_nodes(conn)) == {"n1", "n2"}


def test_pings_for_unknown_node_returns_empty(tmp_path):
    conn = tripdb.connect(tmp_path / "trips.db")
    assert tripdb.pings_for_node(conn, "ghost") == []
    assert tripdb.distinct_nodes(conn) == []
