import sqlite3
from flask import Flask, render_template_string, request
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
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER,
        session_date TEXT
    )
    """)

    conn.commit()
    conn.close()


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

.board-container{
    overflow:auto;
    max-height:75vh;
    border:1px solid #ccc;
}

/* table layout */

table{
    border-collapse:collapse;
    min-width:900px;
}

th,td{
    border:1px solid #ccc;
    padding:8px;
    text-align:center;
    background:white;
}

/* freeze header row */

thead th{
    position:sticky;
    top:0;
    background:#f4f4f4;
    z-index:3;
}

/* freeze client column */

tbody td:first-child,
thead th:first-child{
    position:sticky;
    left:0;
    background:white;
    font-weight:bold;
    text-align:left;
    padding-left:12px;
    z-index:4;
}

/* bigger clickable checkboxes */

input[type=checkbox]{
    width:22px;
    height:22px;
    cursor:pointer;
}

</style>

<div class="board-container">

<table>

<thead>

<tr>
<th>Client</th>

{% for d in dates %}
<th>{{d}}</th>
{% endfor %}

</tr>

</thead>

<tbody>

{% for c in clients %}

<tr>

<td>{{c['full_name']}}</td>

{% for d in dates %}

{% set key = c['id'] ~ "|" ~ d %}

<td>

<input type="checkbox"
name="{{key}}"
value="1"

{% if (c['id'],d) in lookup %}
checked
{% endif %}

>

</td>

{% endfor %}

</tr>

{% endfor %}

</tbody>

</table>

</div>

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
