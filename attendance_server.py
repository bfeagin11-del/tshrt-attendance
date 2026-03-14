import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime
import os

DB_PATH = "tshrt.db"

app = Flask(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY,
        full_name TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        status TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        challenge_id INTEGER,
        session_date TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_clients():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, full_name
            FROM clients
            ORDER BY full_name
        """).fetchall()
        conn.close()
    except Exception:
        rows = []

    return {"Challenge": rows}


def get_active_challenge():
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("""
            SELECT id
            FROM challenges
            WHERE status='active'
            LIMIT 1
        """).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def log_attendance(client_id):
    today = datetime.today().date().isoformat()
    challenge_id = get_active_challenge()

    try:
        conn = sqlite3.connect(DB_PATH)

        existing = conn.execute("""
            SELECT id
            FROM attendance
            WHERE client_id=? AND session_date=?
        """, (client_id, today)).fetchone()

        if existing:
            conn.close()
            return

        conn.execute("""
            INSERT INTO attendance (client_id, challenge_id, session_date)
            VALUES (?, ?, ?)
        """, (client_id, challenge_id, today))

        conn.commit()
        conn.close()
    except Exception:
        pass


@app.route("/")
def home():
    return """
    <h1>TSHRT Attendance</h1>
    <p><a href="/checkin">Client Check-In</a></p>
    <p><a href="/coach">Coach Dashboard</a></p>
    <p><a href="/coach_checkin">Coach Bulk Check-In</a></p>
    """


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    if request.method == "POST":
        client_id = request.form["client_id"]
        log_attendance(client_id)
        return "✅ Check-in recorded"

    groups = get_clients()

    html = """
    <h1>TSHRT Class Check-In</h1>
    <p>Tap your name to check in.</p>

    <style>
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
        gap: 10px;
    }
    button {
        font-size: 18px;
        padding: 15px;
        border-radius: 8px;
        border: none;
        background: #2c7be5;
        color: white;
        width: 100%;
    }
    </style>

    <form method="post">
    {% for group, clients in groups.items() %}
        <h3>{{group}}</h3>
        <div class="grid">
        {% for c in clients %}
            <button name="client_id" value="{{c['id']}}">
                {{c['full_name']}}
            </button>
        {% endfor %}
        </div>
    {% endfor %}
    </form>
    """

    return render_template_string(html, groups=groups)


@app.route("/coach")
def coach():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT clients.full_name
            FROM attendance
            JOIN clients ON attendance.client_id = clients.id
            WHERE attendance.session_date = DATE('now')
            ORDER BY clients.full_name
        """).fetchall()
        conn.close()
    except Exception:
        rows = []

    html = """
    <h1>TSHRT Coach Dashboard</h1>
    <h2>Attendance Today</h2>

    {% if rows %}
        <p><b>{{rows|length}} Checked In</b></p>
        {% for r in rows %}
            <p>✔ {{r['full_name']}}</p>
        {% endfor %}
    {% else %}
        <p>No one has checked in yet.</p>
    {% endif %}
    """

    return render_template_string(html, rows=rows)


@app.route("/coach_checkin", methods=["GET", "POST"])
def coach_checkin():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        clients = conn.execute("""
            SELECT id, full_name
            FROM clients
            ORDER BY full_name
        """).fetchall()
        conn.close()
    except Exception:
        clients = []

    if request.method == "POST":
        today = datetime.today().date().isoformat()
        challenge_id = get_active_challenge()
        selected = request.form.getlist("client")

        conn = sqlite3.connect(DB_PATH)

        for cid in selected:
            existing = conn.execute("""
                SELECT id
                FROM attendance
                WHERE client_id=? AND session_date=?
            """, (cid, today)).fetchone()

            if not existing:
                conn.execute("""
                    INSERT INTO attendance (client_id, challenge_id, session_date)
                    VALUES (?, ?, ?)
                """, (cid, challenge_id, today))

        conn.commit()
        conn.close()

        return "✅ Attendance saved"

    html = """
    <h1>Coach Attendance</h1>
    <p>Everyone is checked by default. Uncheck absences.</p>

    <form method="post">
    {% for c in clients %}
        <input type="checkbox" name="client" value="{{c['id']}}" checked>
        {{c['full_name']}}<br>
    {% endfor %}
    <br>
    <button>Submit Attendance</button>
    </form>
    """

    return render_template_string(html, clients=clients)


@app.route("/upload_roster", methods=["POST"])
def upload_roster():
    data = request.get_json()

    if not data:
        return "No data received", 400

    clients = data.get("clients", [])

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY,
        full_name TEXT
    )
    """)

    conn.execute("DELETE FROM clients")

    for c in clients:
        conn.execute(
            "INSERT INTO clients (id, full_name) VALUES (?, ?)",
            (c["id"], c["full_name"])
        )

    conn.commit()
    conn.close()

    return "Roster uploaded successfully"


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
