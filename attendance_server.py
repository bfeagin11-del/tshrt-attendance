import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime

DB_PATH = "tshrt.db"

app = Flask(__name__)


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
    except:
        rows = []

    groups = {"Challenge": rows}
    return groups


def get_active_challenge():
    try:
        conn = sqlite3.connect(DB_PATH)

        row = conn.execute("""
            SELECT id
            FROM challenges
            WHERE status='active'
        """).fetchone()

        conn.close()

        return row[0] if row else None
    except:
        return None


def log_attendance(client_id):

    challenge_id = get_active_challenge()

    if not challenge_id:
        return

    today = datetime.today().date()

    try:
        conn = sqlite3.connect(DB_PATH)

        existing = conn.execute("""
        SELECT id FROM attendance
        WHERE client_id=? AND session_date=?
        """, (client_id, today)).fetchone()

        if existing:
            conn.close()
            return

        conn.execute("""
            INSERT INTO attendance
            (client_id, challenge_id, session_date)
            VALUES (?, ?, ?)
        """, (client_id, challenge_id, today))

        conn.commit()
        conn.close()

    except:
        pass


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

    <form method="post">

    {% for group, clients in groups.items() %}
        <h3>{{group}}</h3>

        {% for c in clients %}
            <button name="client_id" value="{{c['id']}}">
                {{c['full_name']}}
            </button><br><br>
        {% endfor %}

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
    except:
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


if __name__ == "__main__":
    app.run()
