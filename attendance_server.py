print("🔥🔥🔥 THIS IS THE REAL SERVER VERSION 🔥🔥🔥")
from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)

DB_FILE = "attendance.db"


# =========================
# INIT DATABASE (SAFE)
# =========================
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

    # 🔥 ADD COLUMN IF DATABASE ALREADY EXISTS (SAFE)
    try:
        cur.execute("ALTER TABLE clients ADD COLUMN in_challenge INTEGER DEFAULT 1")
    except:
        pass

    conn.commit()
    conn.close()


# =========================
# LOAD DATA (FOR DEBUG/BOARD)
# =========================
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
    if not row[1]:  # skip bad names
        continue

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


# =========================
# SYNC ENDPOINT
# =========================
print("🔥 RAW CLIENT DATA:", data["clients"][:2])
@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    data = request.get_json()

    if not data or "clients" not in data:
        return jsonify({"ok": False, "error": "No client data received"}), 400

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # 🔥 FULL CLEAN REBUILD (PERMANENT FIX)
    cur.execute("DELETE FROM clients")

    clean_count = 0

for c in data["clients"]:
    cid = c.get("client_id")
    name = c.get("display_name")

    print("CHECKING:", cid, "|", name)

    # Only skip if truly broken
    if cid is None or name is None:
        print("❌ SKIPPED BAD ROW")
        continue

    cur.execute("""
        INSERT INTO clients (client_id, display_name, snapshot_score, baseline_score, in_challenge)
        VALUES (?, ?, ?, ?, 1)
    """, (
        cid,
        str(name),
        int(c.get("snapshot_score", 0)),
        int(c.get("baseline_score", 0))
    ))

    clean_count += 1

# =========================
# CHECK-IN PAGE
# =========================
@app.route("/checkin")
def checkin():
    data = load_data()

    html = """
    <html>
    <body style="background:black; color:white; font-family:Arial; text-align:center;">
    <h1 style="color:gold;">Client Check-In</h1>
    """

    for c in data["clients"]:
        html += f"""
        <div style="margin:10px;">
            <form method="POST" action="/checkin_submit">
                <input type="hidden" name="client_id" value="{c['client_id']}">
                <button style="font-size:20px;">{c['display_name']}</button>
            </form>
        </div>
        """

    html += "</body></html>"
    return html


@app.route("/checkin_submit", methods=["POST"])
def checkin_submit():
    cid = request.form.get("client_id")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("INSERT INTO attendance (client_id, date) VALUES (?, date('now'))", (cid,))
    conn.commit()
    conn.close()

    return "Checked In"


# =========================
# LEADERBOARD
# =========================
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

    html = """
    <html>
    <head>
        <style>
            body { background:black; color:white; text-align:center; font-family:Arial; }
            h1 { color:gold; font-size:48px; }
            .row { font-size:26px; margin:10px; border-bottom:1px solid gold; padding:10px; }
        </style>
    </head>
    <body>
        <h1>🔥 CHALLENGE LEADERBOARD 🔥</h1>
    """

    for i, r in enumerate(rows, 1):
        html += f'<div class="row">#{i} {r[0]} | C:{r[1]} | L:{r[2]}</div>'

    html += "</body></html>"

    return html


# =========================
# DEBUG ROUTE
# =========================
@app.route("/debug/roster")
def debug_roster():
    return jsonify(load_data())


# =========================
# RUN
# =========================
if __name__ == "__main__":
    init_db()
    print("🔥🔥🔥 CLEAN SERVER RUNNING 🔥🔥🔥")
    app.run(host="0.0.0.0", port=10000)
