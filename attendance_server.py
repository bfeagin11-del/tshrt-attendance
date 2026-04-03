from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_FILE = "attendance.db"

# ------------------ INIT DB ------------------
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

# ------------------ PING ------------------
@app.route("/ping")
def ping():
    return {"status": "awake"}

# ------------------ SYNC ------------------
@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    data = request.get_json()
    clients = data.get("clients", data)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("DELETE FROM clients")

    for c in clients:
        name = c.get("display_name")
        if not name:
            continue

        cur.execute("""
        INSERT INTO clients VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            c.get("first_name", ""),
            c.get("last_name", ""),
            c.get("group_name", ""),
            c.get("attendance_count", 0),
            c.get("current_score", 0),
            c.get("lifetime_score", 0),
        ))

    conn.commit()
    conn.close()
    return {"ok": True}

# ------------------ GET CLIENTS ------------------
def get_clients():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients ORDER BY last_name")
    rows = cur.fetchall()
    conn.close()

    return [{
        "display_name": r[0],
        "first_name": r[1],
        "last_name": r[2],
        "group_name": r[3],
        "attendance_count": r[4],
        "current_score": r[5],
        "lifetime_score": r[6],
    } for r in rows]

# ------------------ GET ATTENDANCE ------------------
def get_attendance_map(date):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT display_name, attended FROM attendance WHERE class_date = ?", (date,))
    rows = cur.fetchall()
    conn.close()

    return {r[0]: r[1] for r in rows}

# ------------------ SAVE ATTENDANCE ------------------
def save_attendance(date, names):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # prevent double scoring
    cur.execute("SELECT COUNT(*) FROM attendance WHERE class_date = ? AND attended = 1", (date,))
    already_scored = cur.fetchone()[0] > 0

    cur.execute("DELETE FROM attendance WHERE class_date = ?", (date,))

    clients = get_clients()

    for c in clients:
        name = c["display_name"]
        attended = 1 if name in names else 0

        cur.execute("INSERT INTO attendance (class_date, display_name, attended) VALUES (?, ?, ?)",
                    (date, name, attended))

        if attended and not already_scored:
            cur.execute("""
            UPDATE clients
            SET attendance_count = attendance_count + 1,
                current_score = current_score + 1,
                lifetime_score = lifetime_score + 1
            WHERE display_name = ?
            """, (name,))

    conn.commit()
    conn.close()

# ------------------ CHECKIN ------------------
@app.route("/checkin", methods=["GET", "POST"])
def checkin():

    date = request.args.get("class_date") or datetime.now().strftime("%Y-%m-%d")

    if request.method == "POST":
        names = request.form.getlist("attended")
        date = request.form.get("class_date")

        save_attendance(date, names)

        return redirect(url_for("checkin", class_date=date, saved=1))

    clients = get_clients()
    attendance = get_attendance_map(date)

    return render_template_string("""
<!doctype html>
<html>
<head>
<title>TSHRT Check-In</title>
</head>
<body style="background:black;color:white;font-family:Arial;padding:20px;">

<h1 style="color:gold;text-align:center;">TSHRT Daily Check-In</h1>

<div style="text-align:center;margin-bottom:10px;">
<button onclick="wake()">⚡ Wake Server</button>
</div>

{% if request.args.get('saved') %}
<div style="color:lime;text-align:center;">Saved Successfully</div>
{% endif %}

<div style="text-align:center;">Date: {{date}}</div>

<form method="get" style="text-align:center;margin:10px;">
<input type="date" name="class_date" value="{{date}}">
<button>Load</button>
</form>

<form method="post">
<input type="hidden" name="class_date" value="{{date}}">

{% for c in clients %}
<div style="margin:5px;border-bottom:1px solid #444;">
{{c.last_name}}, {{c.first_name}}
<input type="checkbox" name="attended" value="{{c.display_name}}"
{% if attendance.get(c.display_name) == 1 %}checked{% endif %}>
</div>
{% endfor %}

<button type="button" onclick="save()">Save Attendance</button>
</form>

<script>
async function save(){
    await fetch('/ping');
    await new Promise(r=>setTimeout(r,1200));
    document.forms[1].submit();
}

function wake(){
    fetch('/ping');
}

setInterval(()=>fetch('/ping'),240000);
</script>

</body>
</html>
""", clients=clients, attendance=attendance, date=date)

# ------------------ DEBUG ------------------
@app.route("/debug")
def debug():
    return {"clients": get_clients()}

# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
