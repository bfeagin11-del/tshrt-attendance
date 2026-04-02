print("🔥 CLEAN SERVER STARTING 🔥")

from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)

DB_FILE = "attendance.db"

# =========================
# INIT DATABASE
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
    conn.close()


# =========================
# LOAD DATA (FROM SQLITE ONLY)
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
        clients.append({
            "client_id": row[0],
            "display_name": row[1],
            "snapshot_score": row[2],
            "baseline_score": row[3],
        })

    conn.close()

    return {"clients": clients}


# =========================
# SYNC ROSTER (SAVE TO SQLITE)
# =========================
@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    incoming = request.get_json()

    if not incoming:
        return jsonify({"ok": False, "error": "No data"}), 400

    clients = incoming.get("clients", [])

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # 🔥 CLEAR OLD DATA (prevents duplicates / None issues)
    cur.execute("DELETE FROM clients")

    for c in clients:
        cid = c.get("client_id")
        name = c.get("display_name")

        if not cid or not name:
            continue  # skip bad entries

        cur.execute("""
        INSERT INTO clients (client_id, display_name, snapshot_score, baseline_score, in_challenge)
        VALUES (?, ?, ?, ?, 1)
        """, (
            cid,
            name,
            int(c.get("snapshot_score", 0)),
            int(c.get("baseline_score", 0))
        ))

    conn.commit()
    conn.close()

    return jsonify({
        "ok": True,
        "loaded": len(clients)
    })


# =========================
# CHECK-IN PAGE
# =========================
@app.route("/checkin")
def checkin():
    data = load_data()

    html = """
    <html>
    <body style="background:black; color:white; text-align:center; font-family:Arial;">
    <h1 style="color:gold;">Client Check-In</h1>
    """

    for c in data["clients"]:
        html += f"""
        <form method="POST" action="/checkin_submit" style="margin:10px;">
            <input type="hidden" name="client_id" value="{c['client_id']}">
            <button style="font-size:20px;">{c['display_name']}</button>
        </form>
        """

    html += "</body></html>"
    return html


# =========================
# CHECK-IN ACTION
# =========================
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

    return "Checked In"


# =========================
# LEADERBOARD
# =========================
@app.route("/board")
def board():
    data = load_data()

    rows = []

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    for c in data["clients"]:
        cid = c["client_id"]

        cur.execute("SELECT COUNT(*) FROM attendance WHERE client_id=?", (cid,))
        attendance_count = cur.fetchone()[0]

        snapshot = int(c.get("snapshot_score", 0))
        baseline = int(c.get("baseline_score", 0))

        current = snapshot + (attendance_count * 2)
        lifetime = baseline + current

        rows.append((c["display_name"], current, lifetime))

    conn.close()

    rows.sort(key=lambda r: -r[1])

    html = """
    <html>
    <body style="background:black; color:white; text-align:center; font-family:Arial;">
    <h1 style="color:gold;">🔥 CHALLENGE LEADERBOARD 🔥</h1>
    """

    for i, r in enumerate(rows, 1):
        html += f"<div style='margin:10px; font-size:24px;'>#{i} {r[0]} | C:{r[1]} | L:{r[2]}</div>"

    html += "</body></html>"

    return html


# =========================
# DEBUG
# =========================
@app.route("/debug/roster")
def debug_roster():
    return jsonify(load_data())


# =========================
# RUN
# =========================
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)
