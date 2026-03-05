import sqlite3
from flask import Flask, render_template_string, request, redirect
from datetime import datetime

app = Flask(__name__)

DB_PATH = "tshrt.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT,
        group_name TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        session_date TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS class_state (
        id INTEGER PRIMARY KEY,
        open INTEGER
    )
    """)

    row = conn.execute("SELECT * FROM class_state").fetchone()

    if not row:
        conn.execute("INSERT INTO class_state (id,open) VALUES (1,0)")

    conn.commit()
    conn.close()


def class_open():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT open FROM class_state WHERE id=1").fetchone()
    conn.close()
    return row[0] == 1


def set_class_state(val):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE class_state SET open=?", (val,))
    conn.commit()
    conn.close()


def get_clients():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
    SELECT id,full_name,group_name
    FROM clients
    ORDER BY full_name
    """).fetchall()

    conn.close()

    groups = {}

    for r in rows:
        g = r["group_name"]

        if g not in groups:
            groups[g] = []

        groups[g].append(r)

    return groups


@app.route("/checkin", methods=["GET","POST"])
def checkin():

    if not class_open():
        return "Check-in closed"

    if request.method == "POST":

        cid = request.form["client_id"]

        conn = sqlite3.connect(DB_PATH)

        conn.execute("""
        INSERT INTO attendance (client_id,session_date)
        VALUES (?,?)
        """,(cid, datetime.today().date()))

        conn.commit()
        conn.close()

        return "Check-in recorded"

    groups = get_clients()

    html = """
    <h1>TSHRT Class Check-In</h1>

    <form method="post">

    {% for g,clients in groups.items() %}

        <h2>{{g}}</h2>

        {% for c in clients %}

            <button name="client_id" value="{{c['id']}}">
            {{c['full_name']}}
            </button><br><br>

        {% endfor %}

    {% endfor %}

    </form>
    """

    return render_template_string(html, groups=groups)


@app.route("/coach_control")
def coach_control():

    status = "OPEN" if class_open() else "CLOSED"

    html = """
    <h1>TSHRT Coach Control</h1>

    <p>Status: {{status}}</p>

    <form method="post" action="/open">
        <button type="submit">OPEN CLASS</button>
    </form>

    <br>

    <form method="post" action="/close">
        <button type="submit">CLOSE CLASS</button>
    </form>

    <br><br>

    <a href="/add">Add Client</a>
    """

    return render_template_string(html, status=status)


@app.route("/open", methods=["POST"])
def open_class():
    set_class_state(1)
    return redirect("/coach_control")


@app.route("/close", methods=["POST"])
def close_class():
    set_class_state(0)
    return redirect("/coach_control")


@app.route("/add", methods=["GET","POST"])
def add():

    if request.method == "POST":

        name = request.form["name"]
        group = request.form["group"]

        conn = sqlite3.connect(DB_PATH)

        conn.execute("""
        INSERT INTO clients (full_name,group_name)
        VALUES (?,?)
        """,(name,group))

        conn.commit()
        conn.close()

        return redirect("/coach_control")

    html = """
    <h1>Add Client</h1>

    <form method="post">

    Name:<br>
    <input name="name"><br><br>

    Group:<br>
    <input name="group" value="ABC"><br><br>

    <button>Add</button>

    </form>
    """

    return render_template_string(html)


@app.route("/coach")
def coach():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
    SELECT clients.full_name,attendance.session_date
    FROM attendance
    JOIN clients ON attendance.client_id=clients.id
    ORDER BY attendance.session_date DESC
    """).fetchall()

    conn.close()

    html = """
    <h1>TSHRT Coach Dashboard</h1>

    {% for r in rows %}

    <p>{{r['full_name']}} - {{r['session_date']}}</p>

    {% endfor %}
    """

    return render_template_string(html, rows=rows)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000)
