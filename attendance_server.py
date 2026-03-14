import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime
import os

DB_PATH = "tshrt.db"

app = Flask(__name__)


# ---------------- DATABASE ----------------

def init_db():

    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY,
        full_name TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        session_date TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- CLIENT LIST ----------------

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


# ---------------- CHALLENGE BOARD ----------------

@app.route("/challenge_board", methods=["GET","POST"])
def challenge_board():

    dates = [
        "2026-03-10","2026-03-12",
        "2026-03-17","2026-03-19",
        "2026-03-24","2026-03-26",
        "2026-03-31","2026-04-02",
        "2026-04-07","2026-04-09",
        "2026-04-14","2026-04-16"
    ]

    clients = get_clients()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    attendance = conn.execute("""
        SELECT client_id, session_date
        FROM attendance
    """).fetchall()

    conn.close()

    lookup = {(a["client_id"], a["session_date"]) for a in attendance}


    # -------- SAVE BULK ATTENDANCE --------

    if request.method == "POST":

        conn = sqlite3.connect(DB_PATH)

        conn.execute("DELETE FROM attendance")

        for key in request.form:

            cid, date = key.split("|")

            conn.execute("""
                INSERT INTO attendance (client_id, session_date)
                VALUES (?,?)
            """,(cid,date))

        conn.commit()
        conn.close()

        return "Attendance Updated"


    html = """

    <h1>TSHRT Challenge Attendance</h1>

    <form method="post">

    <style>

    table{border-collapse:collapse}

    td,th{padding:8px;border:1px solid #ccc;text-align:center}

    input[type=checkbox]{width:20px;height:20px}

    </style>

    <table>

    <tr>

        <th>Client</th>

        {% for d in dates %}
        <th>{{d}}</th>
        {% endfor %}

    </tr>

    {% for c in clients %}

    <tr>

        <td>{{c['full_name']}}</td>

        {% for d in dates %}

        {% set key = c['id'] ~ "|" ~ d %}

        <td>

        <input type="checkbox"
        name="{{key}}"

        {% if (c['id'],d) in lookup %}checked{% endif %}

        >

        </td>

        {% endfor %}

    </tr>

    {% endfor %}

    </table>

    <br>

    <button type="submit">Save Attendance</button>

    </form>

    """

    return render_template_string(
        html,
        clients=clients,
        dates=dates,
        lookup=lookup
    )


# ---------------- ROSTER UPLOAD ----------------

@app.route("/upload_roster", methods=["POST"])
def upload_roster():

    data = request.get_json()

    clients = data.get("clients", [])

    conn = sqlite3.connect(DB_PATH)

    conn.execute("DELETE FROM clients")

    for c in clients:

        conn.execute("""
            INSERT INTO clients (id, full_name)
            VALUES (?,?)
        """,(c["id"],c["full_name"]))

    conn.commit()
    conn.close()

    return "Roster uploaded successfully"


init_db()


if __name__ == "__main__":

    port = int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0", port=port)
