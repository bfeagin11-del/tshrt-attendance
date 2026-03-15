import os
import sqlite3
from datetime import date

from flask import Flask, render_template_string, request, redirect, url_for

DB_PATH = "tshrt.db"

app = Flask(__name__)


# ---------------- DATABASE ----------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL UNIQUE
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        session_date TEXT NOT NULL,
        UNIQUE(client_id, session_date)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS finalized_dates (
        session_date TEXT PRIMARY KEY
    )
    """)

    conn.commit()
    conn.close()


# ---------------- HELPERS ----------------

def get_clients():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, full_name
        FROM clients
        ORDER BY full_name
    """).fetchall()
    conn.close()
    return rows


def get_attendance_lookup():
    conn = get_conn()
    rows = conn.execute("""
        SELECT client_id, session_date
        FROM attendance
    """).fetchall()
    conn.close()
    return {(row["client_id"], row["session_date"]) for row in rows}


def get_finalized_dates():
    conn = get_conn()
    rows = conn.execute("""
        SELECT session_date
        FROM finalized_dates
    """).fetchall()
    conn.close()
    return {row["session_date"] for row in rows}


def is_future_date(date_str: str) -> bool:
    return date_str > date.today().isoformat()


def challenge_dates():
    return [
        "2026-03-10", "2026-03-12",
        "2026-03-17", "2026-03-19",
        "2026-03-24", "2026-03-26",
        "2026-03-31", "2026-04-02",
        "2026-04-07", "2026-04-09",
        "2026-04-14", "2026-04-16",
    ]


def challenge_date_labels():
    return {
        "2026-03-10": "Mon 3/10",
        "2026-03-12": "Wed 3/12",
        "2026-03-17": "Mon 3/17",
        "2026-03-19": "Wed 3/19",
        "2026-03-24": "Mon 3/24",
        "2026-03-26": "Wed 3/26",
        "2026-03-31": "Mon 3/31",
        "2026-04-02": "Wed 4/2",
        "2026-04-07": "Mon 4/7",
        "2026-04-09": "Wed 4/9",
        "2026-04-14": "Mon 4/14",
        "2026-04-16": "Wed 4/16",
    }


# ---------------- HOME ----------------

@app.route("/")
def home():
    return """
    <h1>TSHRT Attendance</h1>
    <p><a href="/checkin">Client Check-In</a></p>
    <p><a href="/coach">Coach Dashboard</a></p>
    <p><a href="/coach_checkin">Coach Bulk Check-In</a></p>
    <p><a href="/challenge_board">Challenge Attendance Board</a></p>
    """


# ---------------- CLIENT CHECK-IN ----------------

@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        today = date.today().isoformat()

        if client_id:
            conn = get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO attendance (client_id, session_date) VALUES (?, ?)",
                (client_id, today),
            )
            conn.commit()
            conn.close()

        return "✅ Check-in recorded"

    clients = get_clients()

    html = """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>TSHRT Class Check-In</title>
    <style>
    body { font-family: Arial, Helvetica, sans-serif; margin: 16px; }
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 10px;
    }
    button {
        width: 100%;
        padding: 14px;
        font-size: 17px;
        border: none;
        border-radius: 8px;
        background: #2c7be5;
        color: white;
        cursor: pointer;
    }
    </style>
    </head>
    <body>
    <h1>TSHRT Class Check-In</h1>
    <p>Tap your name to check in.</p>

    <form method="post">
        <div class="grid">
        {% for c in clients %}
            <button name="client_id" value="{{ c['id'] }}">{{ c['full_name'] }}</button>
        {% endfor %}
        </div>
    </form>
    </body>
    </html>
    """
    return render_template_string(html, clients=clients)


# ---------------- COACH DASHBOARD ----------------

@app.route("/coach")
def coach():
    today = date.today().isoformat()

    conn = get_conn()
    rows = conn.execute("""
        SELECT c.full_name
        FROM attendance a
        JOIN clients c ON a.client_id = c.id
        WHERE a.session_date = ?
        ORDER BY c.full_name
    """, (today,)).fetchall()
    conn.close()

    html = """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>TSHRT Coach Dashboard</title>
    <style>
    body { font-family: Arial, Helvetica, sans-serif; margin: 16px; }
    </style>
    </head>
    <body>
    <h1>TSHRT Coach Dashboard</h1>
    <h2>Attendance Today</h2>

    {% if rows %}
        <p><b>{{ rows|length }} Checked In</b></p>
        {% for r in rows %}
            <p>✔ {{ r['full_name'] }}</p>
        {% endfor %}
    {% else %}
        <p>No one has checked in yet.</p>
    {% endif %}
    </body>
    </html>
    """
    return render_template_string(html, rows=rows)


# ---------------- COACH BULK CHECK-IN ----------------

@app.route("/coach_checkin", methods=["GET", "POST"])
def coach_checkin():
    clients = get_clients()
    today = date.today().isoformat()

    if request.method == "POST":
        selected = request.form.getlist("client")

        conn = get_conn()
        conn.execute("DELETE FROM attendance WHERE session_date = ?", (today,))

        for cid in selected:
            conn.execute(
                "INSERT OR IGNORE INTO attendance (client_id, session_date) VALUES (?, ?)",
                (cid, today),
            )

        conn.commit()
        conn.close()

        return "✅ Attendance saved"

    html = """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>TSHRT Coach Attendance</title>
    <style>
    body { font-family: Arial, Helvetica, sans-serif; margin: 16px; }
    </style>
    </head>
    <body>
    <h1>Coach Attendance</h1>
    <p>Everyone is checked by default. Uncheck absences.</p>

    <form method="post">
    {% for c in clients %}
        <label>
            <input type="checkbox" name="client" value="{{ c['id'] }}" checked>
            {{ c['full_name'] }}
        </label><br>
    {% endfor %}
    <br>
    <button type="submit">Submit Attendance</button>
    </form>
    </body>
    </html>
    """
    return render_template_string(html, clients=clients)


# ---------------- CHALLENGE BOARD ----------------

@app.route("/challenge_board", methods=["GET", "POST"])
def challenge_board():
    dates = challenge_dates()

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "save_board":
            finalized = get_finalized_dates()
            conn = get_conn()

            for d in dates:
                if d not in finalized:
                    conn.execute("DELETE FROM attendance WHERE session_date = ?", (d,))

            for key in request.form:
                if "|" not in key:
                    continue

                cid, d = key.split("|", 1)

                if d in finalized:
                    continue

                conn.execute(
                    "INSERT OR IGNORE INTO attendance (client_id, session_date) VALUES (?, ?)",
                    (cid, d),
                )

            conn.commit()
            conn.close()

            return redirect(url_for("challenge_board"))

        if action == "finalize_date":
            selected_date = request.form.get("finalize_date", "").strip()

            if selected_date in dates:
                conn = get_conn()
                conn.execute(
                    "INSERT OR IGNORE INTO finalized_dates (session_date) VALUES (?)",
                    (selected_date,),
                )
                conn.commit()
                conn.close()

            return redirect(url_for("challenge_board"))

    clients = get_clients()
    lookup = get_attendance_lookup()
    finalized_dates = get_finalized_dates()
    labels = challenge_date_labels()

    totals = {}
    for c in clients:
        totals[c["id"]] = sum(1 for d in dates if (c["id"], d) in lookup)

    html = """
    <!doctype html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>TSHRT Challenge Attendance</title>
    <style>
    body {
        font-family: Arial, Helvetica, sans-serif;
        margin: 16px;
    }

    h1 {
        margin-bottom: 8px;
    }

    .note {
        color: #555;
        margin-bottom: 10px;
    }

    .legend {
        margin: 10px 0 14px 0;
    }

    .legend span {
        margin-right: 14px;
    }

    .topbar {
        margin-bottom: 14px;
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
    }

    .board-wrap {
        overflow: auto;
        max-width: 100%;
        border: 1px solid #ccc;
    }

    table {
        border-collapse: collapse;
        min-width: 1200px;
    }

    th, td {
        border: 1px solid #ccc;
        padding: 8px;
        text-align: center;
        background: white;
    }

    thead th {
        position: sticky;
        top: 0;
        background: #f0f0f0;
        z-index: 3;
    }

    thead th:first-child,
    tbody td:first-child {
        position: sticky;
        left: 0;
        z-index: 4;
        text-align: left;
        min-width: 220px;
        font-weight: bold;
    }

    thead th:first-child {
        background: #f0f0f0;
    }

    tbody td:first-child {
        background: white;
    }

    thead th:last-child,
    tbody td:last-child {
        position: sticky;
        right: 0;
        z-index: 4;
        min-width: 80px;
        font-weight: bold;
    }

    thead th:last-child {
        background: #f0f0f0;
    }

    tbody td:last-child {
        background: white;
    }

    input[type=checkbox] {
        width: 22px;
        height: 22px;
        cursor: pointer;
        accent-color: #5cb85c;
    }

    .future {
        width: 22px;
        height: 22px;
        display: inline-block;
        background: #ddd;
        border: 1px solid #ccc;
        border-radius: 4px;
    }

    .locked-col {
        outline: 2px solid #666;
        outline-offset: -2px;
    }

    button, select {
        padding: 8px 12px;
        font-size: 14px;
    }
    </style>
    </head>
    <body>

    <h1>TSHRT Challenge Attendance</h1>
    <div class="note">Edit attendance on the board, then save. Finalize a class date only after you verify it for points.</div>

    <div class="legend">
        <span>✔ Green = attended</span>
        <span>⬜ White = open</span>
        <span>⬛ Gray = future</span>
        <span>Border = finalized/locked</span>
    </div>

    <form method="post" class="topbar">
        <input type="hidden" name="action" value="finalize_date">
        <label for="finalize_date"><strong>Finalize Class Attendance:</strong></label>
        <select name="finalize_date" id="finalize_date">
            {% for d in dates %}
            <option value="{{ d }}">{{ labels[d] }}</option>
            {% endfor %}
        </select>
        <button type="submit">Finalize Selected Class</button>
    </form>

    <form method="post">
        <input type="hidden" name="action" value="save_board">

        <div class="board-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Client</th>
                        {% for d in dates %}
                        <th class="{% if d in finalized_dates %}locked-col{% endif %}">{{ labels[d] }}</th>
                        {% endfor %}
                        <th>Total</th>
                    </tr>
                </thead>
                <tbody>
                    {% for c in clients %}
                    <tr>
                        <td>{{ c['full_name'] }}</td>

                        {% for d in dates %}
                        {% set key = c['id'] ~ "|" ~ d %}
                        {% set checked = (c['id'], d) in lookup %}
                        {% set locked = d in finalized_dates %}
                        {% set future = d in future_dates %}

                        <td class="{% if locked %}locked-col{% endif %}">
                            {% if future %}
                                <span class="future"></span>
                            {% else %}
                                <input
                                    type="checkbox"
                                    name="{{ key }}"
                                    value="1"
                                    {% if checked %}checked{% endif %}
                                    {% if locked %}disabled{% endif %}
                                >
                            {% endif %}
                        </td>
                        {% endfor %}

                        <td>{{ totals[c['id']] }} / 12</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div style="margin-top: 14px;">
            <button type="submit">Save Attendance</button>
        </div>
    </form>

    </body>
    </html>
    """

    return render_template_string(
        html,
        clients=clients,
        dates=dates,
        labels=labels,
        lookup=lookup,
        finalized_dates=finalized_dates,
        future_dates={d for d in dates if is_future_date(d)},
        totals=totals,
    )


# ---------------- ROSTER SYNC ----------------

@app.route("/upload_roster", methods=["POST"])
def upload_roster():
    try:
        data = request.get_json(silent=True) or {}
        incoming = data.get("clients", [])

        conn = get_conn()
        conn.execute("DELETE FROM clients")

        inserted = 0

        for item in incoming:
            name = str(item.get("full_name", "")).strip()

            if not name:
                continue

            conn.execute(
                "INSERT INTO clients (full_name) VALUES (?)",
                (name,),
            )
            inserted += 1

        conn.commit()
        conn.close()

        return f"Roster uploaded successfully ({inserted} clients)"

    except Exception as e:
        return f"Server error: {str(e)}", 500


# ---------------- START ----------------

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
