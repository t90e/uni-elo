"""Wipe all votes and players, then re-import from nse_players.json.
Triggered by setting RESET_DB=1 in Railway env vars.
Remove that var after the deploy to prevent re-running.
"""
import psycopg2
import json
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

PLAYERS_JSON = os.path.join(os.path.dirname(__file__), "nse_players.json")


def reset():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    print("Wiping votes and players...")
    cur.execute("DROP TABLE IF EXISTS votes")
    cur.execute("DROP TABLE IF EXISTS players")

    cur.execute("""
        CREATE TABLE players (
            id          SERIAL PRIMARY KEY,
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

    cur.execute("""
        CREATE TABLE votes (
            id                SERIAL PRIMARY KEY,
            winner_id         INTEGER NOT NULL REFERENCES players(id),
            loser_id          INTEGER NOT NULL REFERENCES players(id),
            winner_elo_before INTEGER,
            loser_elo_before  INTEGER,
            winner_elo_after  INTEGER,
            loser_elo_after   INTEGER,
            voted_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    with open(PLAYERS_JSON, "r", encoding="utf-8") as f:
        players = json.load(f)

    for p in players:
        cur.execute(
            "INSERT INTO players (battletag, team, team_url, image_url) VALUES (%s, %s, %s, %s)",
            (p["battletag"], p["team"], p.get("team_url", ""), p.get("image_url", "")),
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done — reset complete, {len(players)} players imported.")


if __name__ == "__main__":
    reset()
