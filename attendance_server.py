print("🔥 CLEAN SERVER STARTING 🔥")

from flask import Flask, request, jsonify
import sqlite3

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
    data = request.get_json()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("DELETE FROM clients")
    cur.execute("DELETE FROM attendance")

    count = 0

    for c in data.get("clients", []):
        cid = c.get("client_id")
        name = c.get("display_name")

        if not cid or not name:
            continue

        cur.execute("""
            INSERT INTO clients (client_id, display_name, snapshot_score, baseline_score, in_challenge)
            VALUES (?, ?, ?, ?, 1)
        """, (
            cid,
            name,
            int(c.get("snapshot_score", 0)),
            int(c.get("baseline_score", 0))
        ))

        count += 1

    conn.commit()
    conn.close()

    print(f"SYNCED {count} CLIENTS")

    return jsonify({"ok": True, "count": count})


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
        attendance_count = len(data["attendance"].get(cid, []))

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
