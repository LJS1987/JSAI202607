"""개인 GPS 주행 로그 저장소 (SQLite, 신규 의존성 없음).

/api/trip/ping 이 수신한 위치 핑 중 신호 노드 근처(main.py 에서 필터링)만
저장한다. signal_learning.py 가 이 로그를 읽어 교차로별 신호 타이밍을
추정한다.
"""

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    speed_ms REAL NOT NULL,
    node_id TEXT NOT NULL,
    dist_m REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pings_node_ts ON pings(node_id, ts);
"""


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    return conn


def log_ping(
    conn: sqlite3.Connection,
    node_id: str,
    dist_m: float,
    lat: float,
    lon: float,
    speed_ms: float,
    ts: float,
) -> None:
    conn.execute(
        "INSERT INTO pings(ts, lat, lon, speed_ms, node_id, dist_m) VALUES (?, ?, ?, ?, ?, ?)",
        (ts, lat, lon, speed_ms, node_id, dist_m),
    )
    conn.commit()


def pings_for_node(conn: sqlite3.Connection, node_id: str) -> list[tuple[float, float]]:
    """해당 노드 근처 핑을 시간순 (ts, speed_ms) 목록으로."""
    rows = conn.execute(
        "SELECT ts, speed_ms FROM pings WHERE node_id = ? ORDER BY ts", (node_id,)
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def distinct_nodes(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT DISTINCT node_id FROM pings")]
