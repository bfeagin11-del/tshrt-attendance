import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime
import csv
import io

DB_PATH = "attendance.db"

app = Flask(__name__)

CLASS_OPEN = False


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        session_date TEXT
    )
    """)

    conn.commit()
    conn.close()


init_db()


def get_clients():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, full_name
        FROM clients
        ORDER BY full_name
    """).fetchall()

    conn.close()

    return rows


def log_attendance(client_id):

    today = datetime.today().date()

    conn = sqlite3.connect(DB_PATH)

    existing = conn.execute("""
        SELECT id FROM attendance
        WHERE client_id=? AND session_date=?
    """,(client_id, today)).fetchone()

    if existing:
        conn.close()
        return

    conn.execute("""
        INSERT INTO attendance(client_id, session_date)
        VALUES (?,?)
    """,(client_id, today))

    conn.commit()
    conn.close()


@app.route("/checkin", methods=["GET","POST"])
def checkin():

    global CLASS_OPEN

    if not CLASS_OPEN:
        return "Check-in is currently closed."

    if request.method == "POST":

        client_id = request.form["client_id"]
        log_attendance(client_id)

        return "✅ Check-in recorded"

    clients = get_clients()

    html = """
    <h1>TSHRT Class Check-In</h1>

    <form method="post">

    {% for c in clients %}
        <button name="client_id" value="{{c['id']}}">
            {{c['full_name']}}
        </button><br><br>
    {% endfor %}

    </form>
    """

    return render_template_string(html, clients=clients)


@app.route("/coach")
def coach():

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


@app.route("/coach_control")
def coach_control():

    global CLASS_OPEN

    html = """
    <h1>TSHRT Coach Control</h1>

    <p>Class Status: <b>{{status}}</b></p>

    <form method="post" action="/open_class">
        <button type="submit">OPEN CLASS</button>
    </form>

    <br>

    <form method="post" action="/close_class">
        <button type="submit">CLOSE CLASS</button>
    </form>
    """

    status = "OPEN" if CLASS_OPEN else "CLOSED"

    return render_template_string(html, status=status)


@app.route("/open_class", methods=["POST"])
def open_class():

    global CLASS_OPEN
    CLASS_OPEN = True

    return "Class opened. Clients may check in."


@app.route("/close_class", methods=["POST"])
def close_class():

    global CLASS_OPEN
    CLASS_OPEN = False

    return "Class closed."


@app.route("/export")
def export():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT clients.full_name, attendance.session_date
        FROM attendance
        JOIN clients ON attendance.client_id = clients.id
        ORDER BY attendance.session_date DESC
    """).fetchall()

    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["Client Name","Date"])

    for r in rows:
        writer.writerow([r["full_name"], r["session_date"]])

    return output.getvalue()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
