import os
import hmac
import hashlib
import time
import random
import uuid as _uuid
import psycopg2
import psycopg2.extras
import psycopg2.pool
from flask import Flask, render_template, jsonify, request, abort, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_pool = None
def _get_pool():
    global _pool
    if _pool is None and DATABASE_URL:
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)
    return _pool

def get_db():
    pool = _get_pool()
    if pool:
        return pool.getconn()
    return psycopg2.connect(DATABASE_URL)

def release_db(conn):
    pool = _get_pool()
    if pool:
        pool.putconn(conn)
    else:
        release_db(conn)


def q(conn, sql, params=None):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(sql, params or ())
    return cur


def elo_expected(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def compute_elo_update(winner_elo, loser_elo, winner_votes, loser_votes):
    k_w = 32 if winner_votes < 10 else 16
    k_l = 32 if loser_votes < 10 else 16
    e_w = elo_expected(winner_elo, loser_elo)
    e_l = elo_expected(loser_elo, winner_elo)
    return round(winner_elo + k_w * (1 - e_w)), round(loser_elo + k_l * (0 - e_l))


def get_client_ip():
    return (request.headers.get("CF-Connecting-IP") or
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or
            request.remote_addr)


def _secret_bytes():
    k = app.config["SECRET_KEY"]
    return k if isinstance(k, bytes) else k.encode()


def make_pair_token(p1_id, p2_id):
    ts = int(time.time())
    msg = f"{p1_id}:{p2_id}:{ts}".encode()
    sig = hmac.new(_secret_bytes(), msg, hashlib.sha256).hexdigest()
    return f"{p1_id}:{p2_id}:{ts}:{sig}"


def verify_pair_token(token, winner_id, loser_id):
    try:
        parts = token.split(":")
        p1, p2, ts, sig = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
    except Exception:
        return False
    if time.time() - ts > 300:  # expires after 5 minutes
        return False
    if {p1, p2} != {winner_id, loser_id}:
        return False
    msg = f"{p1}:{p2}:{ts}".encode()
    expected = hmac.new(_secret_bytes(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def public_player(row):
    return {
        "id":        row["id"],
        "battletag": row["battletag"],
        "team":      row["team"],
        "image_url": row["image_url"],
    }


@app.before_request
def load_voter_id():
    g.voter_id = request.cookies.get("vid") or str(_uuid.uuid4())


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' https://nse.gg data:; "
        "script-src 'self' https://platform.twitter.com; "
        "frame-src https://platform.twitter.com https://syndication.twitter.com; "
        "connect-src 'self' https://api.twitter.com;"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if not request.cookies.get("vid"):
        response.set_cookie(
            "vid", g.voter_id,
            max_age=365 * 24 * 3600,
            httponly=True,
            samesite="Strict",
        )
    return response


# ── Pages ────────────────────────────────────────────────────

@app.route("/")
def index():
    conn = get_db()
    try:
        total_votes = q(conn, "SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
    finally:
        release_db(conn)
    return render_template("index.html", total_votes=total_votes)


@app.route("/leaderboard")
def leaderboard():
    conn = get_db()
    try:
        players = q(conn, """
            SELECT *,
                   CASE WHEN total_votes > 0
                        THEN ROUND(wins * 100.0 / total_votes, 1)
                        ELSE 0 END AS win_rate
            FROM players ORDER BY elo DESC
        """).fetchall()
        total_votes = q(conn, "SELECT COUNT(*) AS n FROM votes").fetchone()["n"]
    finally:
        release_db(conn)
    return render_template(
        "leaderboard.html",
        players=[dict(p) for p in players],
        total_votes=total_votes,
    )


# ── API ──────────────────────────────────────────────────────

@app.route("/api/pair")
@limiter.limit("120 per minute")
def get_pair():
    conn = get_db()
    try:
        if random.random() < 0.5:
            p1 = q(conn, "SELECT * FROM players ORDER BY RANDOM() LIMIT 1").fetchone()
            if p1:
                p2 = q(conn,
                    "SELECT * FROM players WHERE id != %s AND ABS(elo - %s) <= 300 ORDER BY RANDOM() LIMIT 1",
                    (p1["id"], p1["elo"])
                ).fetchone()
                if not p2:
                    p2 = q(conn,
                        "SELECT * FROM players WHERE id != %s ORDER BY RANDOM() LIMIT 1",
                        (p1["id"],)
                    ).fetchone()
            else:
                p1 = p2 = None
        else:
            rows = q(conn, "SELECT * FROM players ORDER BY RANDOM() LIMIT 2").fetchall()
            p1 = rows[0] if len(rows) > 0 else None
            p2 = rows[1] if len(rows) > 1 else None
    finally:
        release_db(conn)

    if not p1 or not p2:
        abort(503)

    token = make_pair_token(p1["id"], p2["id"])
    return jsonify({"player1": public_player(p1), "player2": public_player(p2), "token": token})


@app.route("/api/vote", methods=["POST"])
@limiter.limit("30 per minute")
def vote():
    data = request.get_json(silent=True)
    if not data:
        abort(400)

    try:
        winner_id = int(data["winner_id"])
        loser_id  = int(data["loser_id"])
        token     = str(data["token"])
    except (KeyError, TypeError, ValueError):
        abort(400)

    if winner_id == loser_id:
        abort(400)

    if not verify_pair_token(token, winner_id, loser_id):
        abort(403)

    client_ip = get_client_ip()
    voter_id  = g.voter_id

    conn = get_db()
    try:
        winner = q(conn, "SELECT * FROM players WHERE id=%s", (winner_id,)).fetchone()
        loser  = q(conn, "SELECT * FROM players WHERE id=%s", (loser_id,)).fetchone()

        if not winner or not loser:
            abort(404)

        winner, loser = dict(winner), dict(loser)
        new_w, new_l = compute_elo_update(
            winner["elo"], loser["elo"], winner["total_votes"], loser["total_votes"]
        )

        q(conn, "UPDATE players SET elo=%s, wins=wins+1, total_votes=total_votes+1 WHERE id=%s",
          (new_w, winner_id))
        q(conn, "UPDATE players SET elo=%s, losses=losses+1, total_votes=total_votes+1 WHERE id=%s",
          (new_l, loser_id))
        q(conn,
          "INSERT INTO votes (winner_id,loser_id,winner_elo_before,loser_elo_before,"
          "winner_elo_after,loser_elo_after,ip_address,voter_id) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
          (winner_id, loser_id, winner["elo"], loser["elo"], new_w, new_l, client_ip, voter_id))
        conn.commit()
    finally:
        release_db(conn)

    return jsonify({"ok": True})


# ── Error handlers ───────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):  return jsonify({"error": "bad request"}), 400

@app.errorhandler(403)
def forbidden(e):    return jsonify({"error": "forbidden"}), 403

@app.errorhandler(404)
def not_found(e):    return jsonify({"error": "not found"}), 404

@app.errorhandler(429)
def rate_limited(e): return jsonify({"error": "slow down"}), 429

@app.errorhandler(503)
def unavailable(e):  return jsonify({"error": "unavailable"}), 503


# ── Auto-init / reset DB on startup ─────────────────────────
if DATABASE_URL:
    try:
        if os.environ.get("RESET_DB") == "1":
            from reset_db import reset as _reset_db
            _reset_db()
        else:
            from init_db import init as _init_db
            _init_db()
    except Exception as _e:
        print(f"DB init error: {_e}")


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, port=5000)
