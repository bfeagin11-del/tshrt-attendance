print("🔥 CLEAN SERVER STARTING 🔥")

from flask import Flask, request, jsonify
import sqlite3
import json
import os

DATA_FILE = "roster_data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"clients": [], "attendance": {}}

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

app = Flask(__name__)

DB_FILE = "attendance.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        snapshot_score INTEGER DEFAULT 0,
        baseline_score INTEGER DEFAULT 0,
        in_challenge INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        date TEXT
    )
    """)

    conn.commit()
    conn.close()


def load_data():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    SELECT client_id, display_name, snapshot_score, baseline_score
    FROM clients
    WHERE in_challenge = 1
    """)

    clients = []
    for row in cur.fetchall():
        clients.append({
            "client_id": row[0],
            "display_name": row[1],
            "snapshot_score": row[2],
            "baseline_score": row[3],
        })

    cur.execute("SELECT client_id, date FROM attendance")
    attendance_rows = cur.fetchall()

    attendance = {}
    for cid, date in attendance_rows:
        attendance.setdefault(cid, []).append(date)

    conn.close()

    return {"clients": clients, "attendance": attendance}


@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    incoming = request.get_json()

    if not incoming or "clients" not in incoming:
        return jsonify({"ok": False, "error": "No client data received"}), 400

    # LOAD EXISTING DATA
    data = load_data()

    # REPLACE CLIENT LIST
    data["clients"] = incoming["clients"]

    # KEEP EXISTING ATTENDANCE (DO NOT WIPE)
    if "attendance" not in data:
        data["attendance"] = {}

    # SAVE TO FILE
    save_data(data)

    return jsonify({
        "ok": True,
        "clients_received": len(incoming["clients"])
    })


@app.route("/checkin")
def checkin():
    data = load_data()

    html = "<h1 style='color:gold;'>Check In</h1>"

    for c in data["clients"]:
        html += f"""
        <form method="POST" action="/checkin_submit">
            <input type="hidden" name="client_id" value="{c['client_id']}">
            <button>{c['display_name']}</button>
        </form>
        """

    return html


@app.route("/checkin_submit", methods=["POST"])
def checkin_submit():
    cid = request.form.get("client_id")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO attendance (client_id, date) VALUES (?, date('now'))",
        (cid,)
    )

    conn.commit()
    conn.close()

    return "OK"


@app.route("/board")
def board():
    data = load_data()

    rows = []

    for c in data["clients"]:
        cid = c["client_id"]
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM attendance WHERE client_id=?", (cid,))
        = cur.fetchone()[0]

conn.close()

        snapshot = int(c.get("snapshot_score", 0))
        baseline = int(c.get("baseline_score", 0))

        current = snapshot + (attendance_count * 2)
        lifetime = baseline + current

        rows.append((c["display_name"], current, lifetime))

    rows.sort(key=lambda r: -r[1])

    html = "<h1>🔥 LEADERBOARD 🔥</h1>"

    for i, r in enumerate(rows, 1):
        html += f"<div>#{i} {r[0]} | C:{r[1]} | L:{r[2]}</div>"

    return html


@app.route("/debug/roster")
def debug_roster():
    return jsonify(load_data())


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)
