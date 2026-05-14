"""Run once to create facemash.db and import players from nse_players.json."""
import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "facemash.db")
PLAYERS_JSON = os.path.join(os.path.dirname(__file__), "nse_players.json")


def init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            battletag   TEXT NOT NULL,
            team        TEXT NOT NULL,
            team_url    TEXT,
            image_url   TEXT,
            elo         INTEGER DEFAULT 1000,
            wins        INTEGER DEFAULT 0,
            losses      INTEGER DEFAULT 0,
            total_votes INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            winner_id         INTEGER NOT NULL,
            loser_id          INTEGER NOT NULL,
            winner_elo_before INTEGER,
            loser_elo_before  INTEGER,
            winner_elo_after  INTEGER,
            loser_elo_after   INTEGER,
            voted_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (winner_id) REFERENCES players(id),
            FOREIGN KEY (loser_id)  REFERENCES players(id)
        )
    """)

    existing = c.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    if existing > 0:
        print(f"Database already has {existing} players — skipping import.")
        conn.close()
        return

    with open(PLAYERS_JSON, "r", encoding="utf-8") as f:
        players = json.load(f)

    for p in players:
        c.execute(
            "INSERT INTO players (battletag, team, team_url, image_url) VALUES (?,?,?,?)",
            (p["battletag"], p["team"], p.get("team_url", ""), p.get("image_url", "")),
        )

    conn.commit()
    conn.close()
    print(f"Done — inserted {len(players)} players into {DB_PATH}")


if __name__ == "__main__":
    init()
