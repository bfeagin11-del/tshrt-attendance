from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import sqlite3

print("🔥🔥🔥 PERMANENT VERSION LOADED 🔥🔥🔥")

app = Flask(__name__)

DB_FILE = "attendance.db"
CHALLENGE_START = "2026-03-09"
DAYS = 42


# ==============================
# INIT DB (PERMANENT)
# ==============================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    display_name TEXT,
    snapshot_score INTEGER,
    baseline_score INTEGER,
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


# ==============================
# HELPERS
# ==============================

def get_dates():
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    dates = []
    for i in range(DAYS):
        d = start + timedelta(days=i)
        if d.weekday() in [0, 2]:
            dates.append(d.strftime("%Y-%m-%d"))
    return dates


def safe_int(v, default=0):
    try:
        return int(round(float(v)))
    except:
        return default


# ==============================
# ROUTES
# ==============================

@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


@app.route("/debug/roster")
def debug():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients")
    clients = cur.fetchall()

    cur.execute("SELECT * FROM attendance")
    attendance = cur.fetchall()

    conn.close()

    return jsonify({
        "clients": clients,
        "attendance": attendance
    })


# ==============================
# SYNC (FROM CONTROL PANEL)
# ==============================

@app.route("/api/roster/sync", methods=["POST"])
def sync():
    data = request.get_json() or {}

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    for c in data.get("clients", []):
        name = c.get("name")
        if not name:
            continue

        cid = name.replace(" ", "_").lower()

        snapshot = safe_int(c.get("snapshot", 0))
        lifetime = safe_int(c.get("lifetime", 0))

        cur.execute("""
        INSERT OR REPLACE INTO clients
        VALUES (?, ?, ?, ?)
        """, (cid, name, snapshot, lifetime))

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


# ==============================
# ATTENDANCE TOGGLE (PER DATE)
# ==============================

@app.route("/api/toggle_date", methods=["POST"])
def toggle():
    data = request.get_json()

    cid = data["client_id"]
    date = data["date"]

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    SELECT id FROM attendance WHERE client_id=? AND date=?
    """, (cid, date))

    row = cur.fetchone()

    if row:
        cur.execute("DELETE FROM attendance WHERE id=?", (row[0],))
    else:
        cur.execute("""
        INSERT INTO attendance (client_id, date)
        VALUES (?, ?)
        """, (cid, date))

    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


# ==============================
# CHECK-IN GRID (YOUR STYLE)
# ==============================

@app.route("/checkin")
def checkin():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT client_id, display_name FROM clients")
    clients = cur.fetchall()

    dates = get_dates()

    html = """
    <html>
    <head>
        <style>
            body { background:black; color:white; text-align:center; font-family:Arial; }
            h1 { color:gold; }
            table { margin:auto; border-collapse:collapse; }
            th, td { border:1px solid gold; padding:8px; }
            .box { width:20px; height:20px; cursor:pointer; margin:auto; }
            .present { background:green; }
            .absent { background:white; }
        </style>
    </head>
    <body>
    <h1>🔥 ATTENDANCE BOARD 🔥</h1>
    <table>
    <tr><th>Name</th>
    """

    for d in dates:
        html += f"<th>{d[5:]}</th>"

    html += "</tr>"

    for cid, name in clients:
        html += f"<tr><td>{name}</td>"

        for d in dates:
            cur.execute("""
            SELECT 1 FROM attendance WHERE client_id=? AND date=?
            """, (cid, d))

            present = cur.fetchone() is not None
            cls = "present" if present else "absent"

            html += f"""
            <td>
            <div class="box {cls}" onclick="toggle('{cid}','{d}')"></div>
            </td>
            """

        html += "</tr>"

    conn.close()

    html += """
    </table>

    <script>
    function toggle(cid,date){
        fetch('/api/toggle_date',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({client_id:cid,date:date})
        }).then(()=>location.reload());
    }
    </script>

    </body></html>
    """

    return html


# ==============================
# LEADERBOARD
# ==============================

@app.route("/board")
def board():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    SELECT client_id, display_name, snapshot_score, baseline_score
    FROM clients
    WHERE in_challenge = 1
""")

    rows = []

    for cid, name, snap, base in clients:

        cur.execute("SELECT COUNT(*) FROM attendance WHERE client_id=?", (cid,))
        attendance = cur.fetchone()[0]

        current = snap + (attendance * 2)
        lifetime = base + (attendance * 2)

        rows.append((name, current, lifetime))

    conn.close()

    rows.sort(key=lambda x: -x[1])

    html = "<html><body style='background:black;color:white;text-align:center;font-family:Arial;'>"
    html += "<h1 style='color:gold;'>🔥 CHALLENGE LEADERBOARD 🔥</h1>"

    for i, r in enumerate(rows, 1):
        html += f"<div style='font-size:26px;margin:10px;'>#{i} {r[0]} | C:{r[1]} | L:{r[2]}</div>"

    html += "</body></html>"
    return html


@app.route("/leaderboard")
def leaderboard():
    return board()


# ==============================
# START
# ==============================

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
