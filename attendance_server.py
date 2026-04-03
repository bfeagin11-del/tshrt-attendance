import os
import sqlite3
from datetime import datetime, date
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.environ.get("TSHRT_DB_FILE", os.path.join(BASE_DIR, "attendance.db"))

# Challenge start date for attendance scoring
CHALLENGE_START = date(2026, 3, 9)

# Allowed attendance days for challenge scoring
ALLOWED_WEEKDAYS = {0, 2}  # Monday=0, Wednesday=2


# =========================================================
# DATABASE HELPERS
# =========================================================
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL UNIQUE,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            baseline_score INTEGER DEFAULT 0,
            snapshot_score INTEGER DEFAULT 0,
            group_name TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            class_date TEXT NOT NULL,
            attended INTEGER DEFAULT 0,
            finalized INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(display_name, class_date)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_display_date
        ON attendance(display_name, class_date)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_attendance_date
        ON attendance(class_date)
    """)

    conn.commit()
    conn.close()


# =========================================================
# DATA NORMALIZATION
# =========================================================
def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (ValueError, TypeError):
        return default


def normalize_client(raw):
    """
    Accepts flexible client payloads and returns a normalized record.
    """
    display_name = str(
        raw.get("display_name")
        or raw.get("name")
        or raw.get("client_name")
        or ""
    ).strip()

    first_name = str(raw.get("first_name") or "").strip()
    last_name = str(raw.get("last_name") or "").strip()

    # If no display_name but first/last exist, build one
    if not display_name:
        built = f"{first_name} {last_name}".strip()
        display_name = built

    if not display_name:
        return None

    baseline_score = safe_int(
        raw.get("baseline_score", raw.get("life_score", raw.get("lifetime_base", 0)))
    )
    snapshot_score = safe_int(
        raw.get("snapshot_score", raw.get("current_score_base", raw.get("snap_score", 0)))
    )
    group_name = str(
        raw.get("group_name", raw.get("group", raw.get("team", "")))
    ).strip()

    return {
        "display_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "baseline_score": baseline_score,
        "snapshot_score": snapshot_score,
        "group_name": group_name,
    }


# =========================================================
# ATTENDANCE / SCORE LOGIC
# =========================================================
def is_scoring_day(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d >= CHALLENGE_START and d.weekday() in ALLOWED_WEEKDAYS
    except Exception:
        return False


def count_attendance_for_client(conn, display_name):
    """
    Count only finalized attended classes on scoring days.
    """
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT class_date, attended, finalized
        FROM attendance
        WHERE display_name = ?
    """, (display_name,)).fetchall()

    count = 0
    for row in rows:
        if row["attended"] == 1 and row["finalized"] == 1 and is_scoring_day(row["class_date"]):
            count += 1
    return count


def get_clients_with_scores():
    conn = get_conn()
    cur = conn.cursor()

    clients = cur.execute("""
        SELECT display_name, first_name, last_name, baseline_score, snapshot_score, group_name
        FROM clients
        ORDER BY display_name COLLATE NOCASE ASC
    """).fetchall()

    results = []
    for row in clients:
        attendance_count = count_attendance_for_client(conn, row["display_name"])

        current_score = safe_int(row["snapshot_score"]) + attendance_count
        lifetime_score = safe_int(row["baseline_score"]) + safe_int(row["snapshot_score"]) + attendance_count

        results.append({
            "display_name": row["display_name"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "baseline_score": safe_int(row["baseline_score"]),
            "snapshot_score": safe_int(row["snapshot_score"]),
            "attendance_count": attendance_count,
            "current_score": current_score,
            "lifetime_score": lifetime_score,
            "group_name": row["group_name"] or "",
        })

    conn.close()
    return results


def get_attendance_map_for_date(class_date):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT display_name, attended, finalized
        FROM attendance
        WHERE class_date = ?
    """, (class_date,)).fetchall()

    conn.close()

    result = {}
    for row in rows:
        result[row["display_name"]] = {
            "attended": int(row["attended"]),
            "finalized": int(row["finalized"]),
        }
    return result


def save_attendance_for_date(class_date, attended_names, finalize=False):
    conn = get_conn()
    cur = conn.cursor()

    clients = cur.execute("""
        SELECT display_name
        FROM clients
        ORDER BY display_name COLLATE NOCASE ASC
    """).fetchall()

    attended_set = set(attended_names or [])

    for client in clients:
        name = client["display_name"]
        attended = 1 if name in attended_set else 0

        existing = cur.execute("""
            SELECT id, finalized
            FROM attendance
            WHERE display_name = ? AND class_date = ?
        """, (name, class_date)).fetchone()

        if existing:
            if existing["finalized"] == 1:
                # Locked record - do not overwrite
                continue

            cur.execute("""
                UPDATE attendance
                SET attended = ?, finalized = ?, updated_at = CURRENT_TIMESTAMP
                WHERE display_name = ? AND class_date = ?
            """, (
                attended,
                1 if finalize else 0,
                name,
                class_date
            ))
        else:
            cur.execute("""
                INSERT INTO attendance (display_name, class_date, attended, finalized)
                VALUES (?, ?, ?, ?)
            """, (
                name,
                class_date,
                attended,
                1 if finalize else 0
            ))

    conn.commit()
    conn.close()


# =========================================================
# ROUTES
# =========================================================
@app.route("/")
def home():
    clients = get_clients_with_scores()
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>TSHRT Attendance Home</title>
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #f5f5f5; padding: 30px; }
            h1 { color: gold; }
            a { color: gold; text-decoration: none; font-weight: bold; }
            .box { background: #1b1b1b; border: 1px solid #333; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .count { font-size: 20px; }
        </style>
    </head>
    <body>
        <h1>TSHRT Cloud Attendance System</h1>

        <div class="box">
            <div class="count">Loaded Clients: <strong>{{ clients|length }}</strong></div>
        </div>

        <div class="box">
            <p><a href="/checkin">Open Check-In</a></p>
            <p><a href="/board">Open Coach Board</a></p>
            <p><a href="/display">Open Display Board</a></p>
            <p><a href="/debug/roster">Open Debug Roster</a></p>
        </div>
    </body>
    </html>
    """, clients=clients)


@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    incoming = request.get_json(silent=True)

    if incoming is None:
        return jsonify({
            "ok": False,
            "error": "No JSON payload received"
        }), 400

    if isinstance(incoming, dict) and "clients" in incoming:
        raw_clients = incoming.get("clients", [])
    elif isinstance(incoming, list):
        raw_clients = incoming
    else:
        return jsonify({
            "ok": False,
            "error": "Payload must be a list or an object containing 'clients'"
        }), 400

    normalized = []
    seen = set()

    for raw in raw_clients:
        if not isinstance(raw, dict):
            continue

        client = normalize_client(raw)
        if not client:
            continue

        key = client["display_name"].strip().lower()
        if not key or key in seen:
            continue

        seen.add(key)
        normalized.append(client)

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("BEGIN")

        # Replace roster cleanly, but keep attendance history table intact
        cur.execute("DELETE FROM clients")

        inserted = 0
        for c in normalized:
            cur.execute("""
                INSERT INTO clients (
                    display_name,
                    first_name,
                    last_name,
                    baseline_score,
                    snapshot_score,
                    group_name,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                c["display_name"],
                c["first_name"],
                c["last_name"],
                c["baseline_score"],
                c["snapshot_score"],
                c["group_name"]
            ))
            inserted += 1

        conn.commit()

    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

    total_clients = cur.execute("SELECT COUNT(*) AS count FROM clients").fetchone()["count"]
    conn.close()

    return jsonify({
        "ok": True,
        "inserted": inserted,
        "total_clients": total_clients
    }), 200


@app.route("/debug/roster")
def debug_roster():
    clients = get_clients_with_scores()
    return jsonify({
        "ok": True,
        "count": len(clients),
        "clients": clients
    })


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    today_str = request.values.get("class_date", date.today().strftime("%Y-%m-%d"))

    if request.method == "POST":
        attended_names = request.form.getlist("attended")
        save_attendance_for_date(today_str, attended_names, finalize=False)
        return redirect(url_for("checkin", class_date=today_str))

    clients = get_clients_with_scores()
    attendance_map = get_attendance_map_for_date(today_str)

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>TSHRT Check-In</title>
        <style>
            body { font-family: Arial, sans-serif; background: #101010; color: white; padding: 20px; }
            h1 { color: gold; }
            table { width: 100%; border-collapse: collapse; background: #1a1a1a; }
            th, td { border: 1px solid #333; padding: 10px; text-align: left; }
            th { background: #222; color: gold; }
            tr:nth-child(even) { background: #151515; }
            .btn {
                background: gold; color: black; border: none; padding: 10px 16px;
                font-weight: bold; border-radius: 6px; cursor: pointer;
            }
            .locked { color: #999; font-style: italic; }
            .topbar { margin-bottom: 15px; }
            a { color: gold; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>TSHRT Client Check-In</h1>

        <div class="topbar">
            <form method="get">
                <label><strong>Class Date:</strong></label>
                <input type="date" name="class_date" value="{{ today_str }}">
                <button class="btn" type="submit">Load</button>
                &nbsp;&nbsp;
                <a href="/">Home</a>
            </form>
        </div>

        <form method="post">
            <input type="hidden" name="class_date" value="{{ today_str }}">
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Group</th>
                        <th>Attend</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in clients %}
                    {% set att = attendance_map.get(c.display_name, {}) %}
                    {% set attended = att.get('attended', 0) %}
                    {% set finalized = att.get('finalized', 0) %}
                    <tr>
                        <td>{{ c.display_name }}</td>
                        <td>{{ c.group_name }}</td>
                        <td>
                            {% if finalized %}
                                <input type="checkbox" disabled {% if attended %}checked{% endif %}>
                            {% else %}
                                <input type="checkbox" name="attended" value="{{ c.display_name }}" {% if attended %}checked{% endif %}>
                            {% endif %}
                        </td>
                        <td>
                            {% if finalized %}
                                <span class="locked">Finalized</span>
                            {% else %}
                                Open
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <br>
            <button class="btn" type="submit">Save Check-In</button>
        </form>
    </body>
    </html>
    """, clients=clients, today_str=today_str, attendance_map=attendance_map)


@app.route("/board", methods=["GET", "POST"])
def board():
    class_date = request.values.get("class_date", date.today().strftime("%Y-%m-%d"))

    if request.method == "POST":
        attended_names = request.form.getlist("attended")
        finalize = request.form.get("action") == "finalize"
        save_attendance_for_date(class_date, attended_names, finalize=finalize)
        return redirect(url_for("board", class_date=class_date))

    clients = get_clients_with_scores()
    attendance_map = get_attendance_map_for_date(class_date)

    total_attended_today = sum(
        1 for _, v in attendance_map.items() if v.get("attended", 0) == 1
    )

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>TSHRT Coach Board</title>
        <style>
            body { font-family: Arial, sans-serif; background: #0f0f0f; color: white; padding: 20px; }
            h1 { color: gold; }
            table { width: 100%; border-collapse: collapse; background: #1a1a1a; }
            th, td { border: 1px solid #333; padding: 10px; text-align: left; }
            th { background: #222; color: gold; }
            tr:nth-child(even) { background: #151515; }
            .btn {
                background: gold; color: black; border: none; padding: 10px 16px;
                font-weight: bold; border-radius: 6px; cursor: pointer; margin-right: 10px;
            }
            .locked { color: #999; font-style: italic; }
            .good { color: #7CFC00; font-weight: bold; }
            .meta { margin-bottom: 15px; }
            a { color: gold; text-decoration: none; }
        </style>
    </head>
    <body>
        <h1>TSHRT Challenge Attendance Board</h1>

        <div class="meta">
            <form method="get">
                <label><strong>Class Date:</strong></label>
                <input type="date" name="class_date" value="{{ class_date }}">
                <button class="btn" type="submit">Load</button>
                &nbsp;&nbsp;
                <a href="/">Home</a>
            </form>
            <p><strong>Loaded Clients:</strong> {{ clients|length }}</p>
            <p><strong>Checked In Today:</strong> <span class="good">{{ total_attended_today }}</span></p>
        </div>

        <form method="post">
            <input type="hidden" name="class_date" value="{{ class_date }}">
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Group</th>
                        <th>Baseline</th>
                        <th>Snapshot</th>
                        <th>Attendance</th>
                        <th>Current</th>
                        <th>Lifetime</th>
                        <th>Attend Today</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in clients %}
                    {% set att = attendance_map.get(c.display_name, {}) %}
                    {% set attended = att.get('attended', 0) %}
                    {% set finalized = att.get('finalized', 0) %}
                    <tr>
                        <td>{{ c.display_name }}</td>
                        <td>{{ c.group_name }}</td>
                        <td>{{ c.baseline_score }}</td>
                        <td>{{ c.snapshot_score }}</td>
                        <td>{{ c.attendance_count }}</td>
                        <td>{{ c.current_score }}</td>
                        <td><strong>{{ c.lifetime_score }}</strong></td>
                        <td>
                            {% if finalized %}
                                <input type="checkbox" disabled {% if attended %}checked{% endif %}>
                            {% else %}
                                <input type="checkbox" name="attended" value="{{ c.display_name }}" {% if attended %}checked{% endif %}>
                            {% endif %}
                        </td>
                        <td>
                            {% if finalized %}
                                <span class="locked">Finalized</span>
                            {% else %}
                                Open
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>

            <br>
            <button class="btn" type="submit" name="action" value="save">Save</button>
            <button class="btn" type="submit" name="action" value="finalize">Finalize Selected Class</button>
        </form>
    </body>
    </html>
    """, clients=clients, class_date=class_date, attendance_map=attendance_map, total_attended_today=total_attended_today)


@app.route("/display")
def display():
    clients = sorted(
        get_clients_with_scores(),
        key=lambda x: (-x["lifetime_score"], x["display_name"].lower())
    )

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>TSHRT Display Board</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body { font-family: Arial, sans-serif; background: black; color: white; padding: 20px; }
            h1 { color: gold; text-align: center; font-size: 42px; margin-bottom: 25px; }
            table { width: 100%; border-collapse: collapse; font-size: 24px; }
            th, td { border: 1px solid #333; padding: 14px; text-align: left; }
            th { background: #222; color: gold; }
            tr:nth-child(even) { background: #111; }
            tr:nth-child(odd) { background: #1b1b1b; }
            .rank { width: 80px; text-align: center; font-weight: bold; }
            .score { font-weight: bold; color: gold; }
        </style>
    </head>
    <body>
        <h1>🔥 TSHRT CHALLENGE LEADERBOARD 🔥</h1>
        <table>
            <thead>
                <tr>
                    <th class="rank">#</th>
                    <th>Name</th>
                    <th>Current</th>
                    <th>Lifetime</th>
                </tr>
            </thead>
            <tbody>
                {% for c in clients %}
                <tr>
                    <td class="rank">{{ loop.index }}</td>
                    <td>{{ c.display_name }}</td>
                    <td>C: {{ c.current_score }}</td>
                    <td class="score">L: {{ c.lifetime_score }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body>
    </html>
    """, clients=clients)


# =========================================================
# STARTUP
# =========================================================
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
