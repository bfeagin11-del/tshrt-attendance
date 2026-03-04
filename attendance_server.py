import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime, time

DB_PATH = "tshrt.db"

CHECKIN_START = time(19,10)
CHECKIN_END = time(19,30)

app = Flask(__name__)


def get_clients():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, full_name
        FROM clients
        ORDER BY full_name
    """).fetchall()

    conn.close()

    groups = {"Open Gym":[], "Challenge":[], "Other":[]}

    for r in rows:
        groups["Challenge"].append(r)

    return groups


def get_active_challenge():
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute("""
        SELECT id
        FROM challenges
        WHERE status='active'
    """).fetchone()

    conn.close()

    return row[0] if row else None


def log_attendance(client_id):

    challenge_id = get_active_challenge()

    if not challenge_id:
        return

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        INSERT OR IGNORE INTO attendance
        (client_id, challenge_id, session_date)
        VALUES (?, ?, ?)
    """,(client_id, challenge_id, datetime.today().date()))

    conn.commit()
    conn.close()


@app.route("/checkin", methods=["GET","POST"])
def checkin():

    now = datetime.now().time()

    if not (CHECKIN_START <= now <= CHECKIN_END):
        return "Check-in closed. Window is 19:10–19:30."

    if request.method == "POST":

        client_id = request.form["client_id"]
        log_attendance(client_id)

        return "✅ Check-in recorded"

    groups = get_clients()

    html = """
    <h1>TSHRT Class Check-In</h1>
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

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT clients.full_name, attendance.session_date
        FROM attendance
        JOIN clients ON attendance.client_id = clients.id
        ORDER BY attendance.session_date DESC
    """).fetchall()

    conn.close()

    html = """
    <h1>TSHRT Coach Dashboard</h1>

    <h2>Recent Check-ins</h2>

    {% for r in rows %}
        <p>{{r['full_name']}} - {{r['session_date']}}</p>
    {% endfor %}
    """

    return render_template_string(html, rows=rows)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
