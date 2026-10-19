from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    key           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    employer      TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    location      TEXT,
    url           TEXT,
    detail_path   TEXT,
    posted_text   TEXT,
    description   TEXT,
    score         INTEGER,
    verdict       TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    notified      INTEGER NOT NULL DEFAULT 0,
    closed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_open ON postings(closed_at, score);

CREATE TABLE IF NOT EXISTS state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

CREATE TABLE IF NOT EXISTS mail_seen (
    message_id  TEXT PRIMARY KEY,
    seen_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT NOT NULL,
    source    TEXT NOT NULL,
    employer  TEXT NOT NULL,
    found     INTEGER NOT NULL,
    error     TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = "jobscan.db"):
        # A scheduled scan holds write locks for seconds at a time. The poller
        # used to give up after sqlite's default 5s and fail the whole tick
        # (21 times in two weeks); waiting is always the right answer here.
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release. Idempotent."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(postings)")}
        for name, decl in (
            ("suppressed", "INTEGER NOT NULL DEFAULT 0"),
            ("suppressed_reason", "TEXT"),
            ("notified_at", "TEXT"),
            ("prev_score", "INTEGER"),
            ("prev_verdict", "TEXT"),
            ("scored_at", "TEXT"),
        ):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE postings ADD COLUMN {name} {decl}")

    def save_prior(self, key: str) -> None:
        """Copy the current score/verdict into prev_* before overwriting."""
        self.conn.execute(
            "UPDATE postings SET prev_score = score, prev_verdict = verdict WHERE key = ?",
            (key,))
        self.conn.commit()

    def mark_notified_now(self, key: str) -> None:
        self.conn.execute(
            "UPDATE postings SET notified_at = COALESCE(notified_at, ?) WHERE key = ?",
            (_now(), key))
        self.conn.commit()

    def mark_scored_now(self, key: str) -> None:
        self.conn.execute("UPDATE postings SET scored_at = ? WHERE key = ?", (_now(), key))
        self.conn.commit()

    def mark_suppressed(self, posting: Posting, reason: str) -> None:
        self.conn.execute(
            "UPDATE postings SET suppressed = 1, suppressed_reason = ? WHERE key = ?",
            (reason, posting.key),
        )
        self.conn.commit()

    def all_open(self) -> list[sqlite3.Row]:
        """Every posting we still believe is live, newest first."""
        return self.conn.execute(
            "SELECT * FROM postings WHERE closed_at IS NULL ORDER BY first_seen DESC"
        ).fetchall()

    # -- seen / new -------------------------------------------------------
    def is_known(self, posting: Posting) -> bool:
        cur = self.conn.execute("SELECT 1 FROM postings WHERE key = ?", (posting.key,))
        return cur.fetchone() is not None

    def touch(self, posting: Posting) -> None:
        """Mark an already-known posting as still present in the feed."""
        self.conn.execute(
            "UPDATE postings SET last_seen = ?, closed_at = NULL WHERE key = ?",
            (_now(), posting.key),
        )
        self.conn.commit()

    def record(self, posting: Posting, notified: bool = False) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO postings
               (key, source, employer, external_id, title, location, url,
                detail_path, posted_text, description, score, verdict,
                first_seen, last_seen, notified)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 last_seen   = excluded.last_seen,
                 description = COALESCE(NULLIF(excluded.description,''), postings.description),
                 score     = COALESCE(excluded.score, postings.score),
                 verdict   = COALESCE(NULLIF(excluded.verdict,''), postings.verdict),
                 notified  = MAX(postings.notified, excluded.notified),
                 closed_at = NULL""",
            (
                posting.key, posting.source, posting.employer, posting.external_id,
                posting.title, posting.location, posting.url, posting.detail_path,
                posting.posted_text, posting.description, posting.score,
                posting.verdict, now, now, int(notified),
            ),
        )
        self.conn.commit()

    # -- liveness ---------------------------------------------------------
    def open_notified(self) -> list[Posting]:
        """Roles previously pushed to the phone that we still believe are open.
        These get re-checked each run so you never chase a dead requisition."""
        rows = self.conn.execute(
            "SELECT * FROM postings WHERE notified = 1 AND closed_at IS NULL"
        ).fetchall()
        return [
            Posting(
                source=r["source"], employer=r["employer"],
                external_id=r["external_id"], title=r["title"],
                location=r["location"] or "", url=r["url"] or "",
                detail_path=r["detail_path"] or "", posted_text=r["posted_text"] or "",
                score=r["score"], verdict=r["verdict"] or "",
            )
            for r in rows
        ]

    def open_for_liveness(self, threshold: int) -> list[Posting]:
        """Everything worth re-checking each run: anything pushed to the phone,
        plus anything sitting on the shortlist.

        `notified = 1` alone was not enough. A rescore can lift a role onto the
        shortlist without ever alerting, and those roles were then never
        liveness-checked - so a withdrawn requisition kept its place on the
        dashboard indefinitely. That is worse than missing it: it reads as a
        live opportunity right up until you click it.
        """
        rows = self.conn.execute(
            "SELECT * FROM postings WHERE closed_at IS NULL "
            "AND (notified = 1 OR score >= ?)", (threshold,)
        ).fetchall()
        return [
            Posting(
                source=r["source"], employer=r["employer"],
                external_id=r["external_id"], title=r["title"],
                location=r["location"] or "", url=r["url"] or "",
                detail_path=r["detail_path"] or "", posted_text=r["posted_text"] or "",
                score=r["score"], verdict=r["verdict"] or "",
            )
            for r in rows
        ]

    def mark_closed(self, posting: Posting) -> None:
        self.conn.execute(
            "UPDATE postings SET closed_at = ? WHERE key = ?", (_now(), posting.key)
        )
        self.conn.commit()

    # -- small key/value state -------------------------------------------
    def get_state(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        self.conn.commit()

    # -- mail dedupe ------------------------------------------------------
    def mail_seen(self, message_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM mail_seen WHERE message_id = ?", (message_id,))
        return cur.fetchone() is not None

    def mark_mail_seen(self, message_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO mail_seen (message_id, seen_at) VALUES (?,?)",
            (message_id, _now()),
        )
        self.conn.commit()

    # -- run health -------------------------------------------------------
    def log_run(self, source: str, employer: str, found: int, error: str = "") -> None:
        self.conn.execute(
            "INSERT INTO runs (started, source, employer, found, error) VALUES (?,?,?,?,?)",
            (_now(), source, employer, found, error or None),
        )
        self.conn.commit()

    def silent_sources(self, runs: int = 2) -> list[str]:
        """Employers that returned zero results on the last N runs. Almost
        always means the adapter broke, not that hiring stopped."""
        dead = []
        employers = [
            r["employer"] for r in self.conn.execute("SELECT DISTINCT employer FROM runs")
        ]
        for emp in employers:
            rows = self.conn.execute(
                "SELECT found FROM runs WHERE employer = ? ORDER BY id DESC LIMIT ?",
                (emp, runs),
            ).fetchall()
            if len(rows) >= runs and all(r["found"] == 0 for r in rows):
                dead.append(emp)
        return dead
