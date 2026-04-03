from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)

DB_FILE = "attendance.db"

# -------------------------------
# INIT DB
# -------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            display_name TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            group_name TEXT,
            attendance_count INTEGER DEFAULT 0,
            current_score INTEGER DEFAULT 0,
            lifetime_score INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_date TEXT,
            display_name TEXT,
            attended INTEGER
        )
    """)

    conn.commit()
    conn.close()

init_db()

# -------------------------------
# PING (WAKE SERVER)
# -------------------------------
@app.route("/ping")
def ping():
    return {"status": "awake"}

# -------------------------------
# SYNC ROSTER
# -------------------------------
@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    data = request.get_json()

    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    clients = data.get("clients", data)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("DELETE FROM clients")

    inserted = 0

    for c in clients:
        name = c.get("display_name")
        if not name:
            continue

        cur.execute("""
            INSERT INTO clients (
                display_name,
                first_name,
                last_name,
                group_name,
                attendance_count,
                current_score,
                lifetime_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            c.get("first_name", ""),
            c.get("last_name", ""),
            c.get("group_name", ""),
            c.get("attendance_count", 0),
            c.get("current_score", 0),
            c.get("lifetime_score", 0),
        ))

        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({"ok": True, "inserted": inserted})

# -------------------------------
# GET CLIENTS
# -------------------------------
def get_clients():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients ORDER BY last_name")
    rows = cur.fetchall()
    conn.close()

    clients = []
    for r in rows:
        clients.append({
            "display_name": r[0],
            "first_name": r[1],
            "last_name": r[2],
            "group_name": r[3],
            "attendance_count": r[4],
            "current_score": r[5],
            "lifetime_score": r[6],
        })

    return clients

# -------------------------------
# GET ATTENDANCE MAP
# -------------------------------
def get_attendance_map(class_date):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT display_name, attended
        FROM attendance
        WHERE class_date = ?
    """, (class_date,))

    rows = cur.fetchall()
    conn.close()

    return {r[0]: {"attended": r[1]} for r in rows}

# -------------------------------
# SAVE ATTENDANCE (NO DOUBLE SCORE)
# -------------------------------
def save_attendance(class_date, attended_names):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # check if already scored
    cur.execute("""
        SELECT COUNT(*) FROM attendance
        WHERE class_date = ? AND attended = 1
    """, (class_date,))
    already_scored = cur.fetchone()[0] > 0

    cur.execute("DELETE FROM attendance WHERE class_date = ?", (class_date,))

    clients = get_clients()

    for c in clients:
        name = c["display_name"]
        attended = 1 if name in attended_names else 0

        cur.execute("""
            INSERT INTO attendance (class_date, display_name, attended)
            VALUES (?, ?, ?)
        """, (class_date, name, attended))

        if attended == 1 and not already_scored:
            cur.execute("""
                UPDATE clients
                SET attendance_count = attendance_count + 1,
                    current_score = current_score + 1,
                    lifetime_score = lifetime_score + 1
                WHERE display_name = ?
            """, (name,))

    conn.commit()
    conn.close()

# -------------------------------
# CHECK-IN PAGE
# -------------------------------
@app.route("/checkin", methods=["GET", "POST"])
def checkin():

    class_date = request.args.get("class_date")

    if not class_date:
        class_date = datetime.now().strftime("%Y-%m-%d")

    if request.method == "POST":
        attended_names = request.form.getlist("attended")
        class_date = request.form.get("class_date")

        save_attendance(class_date, attended_names)

        return redirect(url_for("checkin", class_date=class_date))

    clients = get_clients()
    attendance_map = get_attendance_map(class_date)

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
        <title>TSHRT Daily Check-In</title>
    </head>
    <body style="background:black;color:white;font-family:Arial;padding:20px;">

        <h1 style="color:gold;text-align:center;">TSHRT Daily Check-In</h1>

        <div style="text-align:center;margin-bottom:10px;">
            <button onclick="wakeServer()">⚡ Wake Server</button>
        </div>

        <div style="text-align:center;margin-bottom:15px;">
            Class Date: <strong>{{ class_date }}</strong>
        </div>

        <form method="get" style="text-align:center;margin-bottom:20px;">
            <input type="date" name="class_date" value="{{ class_date }}">
            <button type="submit">Load</button>
        </form>

        <form method="post">
            <input type="hidden" name="class_date" value="{{ class_date }}">

            {% for c in clients %}
                {% set att = attendance_map.get(c.display_name, {}) %}
                {% set attended = att.get('attended', 0) %}

                <div style="margin:10px;padding:10px;border:1px solid #444;">
                    {{ c.last_name }}, {{ c.first_name }}
                    <input type="checkbox" name="attended"
                           value="{{ c.display_name }}"
                           {% if attended == 1 %}checked{% endif %}>
                </div>
            {% endfor %}

            <button type="submit">Save Attendance</button>
        </form>

        <script>
        function wakeServer() {
            fetch('/ping');
        }
        setInterval(() => { fetch('/ping'); }, 240000);
        </script>

    </body>
    </html>
    """, clients=clients, class_date=class_date, attendance_map=attendance_map)

# -------------------------------
# DEBUG
# -------------------------------
@app.route("/debug/roster")
def debug_roster():
    return {"clients": get_clients(), "count": len(get_clients()), "ok": True}

# -------------------------------
# RUN
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
