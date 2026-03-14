import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime
import os

DB_PATH = "tshrt.db"

app = Flask(__name__)


# ---------------- DATABASE INIT ----------------

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

    return {"Challenge": rows}


# ---------------- ACTIVE CHALLENGE ----------------

def get_active_challenge():

    conn = sqlite3.connect(DB_PATH)

    row = conn.execute("""
        SELECT id
        FROM challenges
        WHERE status='active'
        LIMIT 1
    """).fetchone()

    conn.close()

    return row[0] if row else 1


# ---------------- LOG ATTENDANCE ----------------

def log_attendance(client_id):

    today = datetime.today().date().isoformat()

    challenge_id = get_active_challenge()

    conn = sqlite3.connect(DB_PATH)

    existing = conn.execute("""
        SELECT id
        FROM attendance
        WHERE client_id=? AND session_date=?
    """,(client_id,today)).fetchone()

    if not existing:

        conn.execute("""
            INSERT INTO attendance
            (client_id,challenge_id,session_date)
            VALUES (?,?,?)
        """,(client_id,challenge_id,today))

    conn.commit()
    conn.close()


# ---------------- HOME ----------------

@app.route("/")
def home():

    return """
    <h1>TSHRT Attendance</h1>

    <p><a href='/checkin'>Client Check-In</a></p>

    <p><a href='/coach'>Coach Dashboard</a></p>

    <p><a href='/coach_checkin'>Coach Bulk Attendance</a></p>

    <p><a href='/challenge_board'>Challenge Attendance Board</a></p>
    """


# ---------------- CLIENT CHECKIN ----------------

@app.route("/checkin",methods=["GET","POST"])
def checkin():

    if request.method=="POST":

        client_id=request.form["client_id"]

        log_attendance(client_id)

        return "✅ Check-in recorded"


    groups=get_clients()

    html="""

    <h1>TSHRT Class Check-In</h1>

    <p>Tap your name to check in</p>

    <style>

    .grid{
        display:grid;
        grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
        gap:10px;
    }

    button{
        font-size:18px;
        padding:15px;
        border-radius:8px;
        border:none;
        background:#2c7be5;
        color:white;
        width:100%;
    }

    </style>

    <form method="post">

    {% for group,clients in groups.items() %}

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

    return render_template_string(html,groups=groups)


# ---------------- COACH DASHBOARD ----------------

@app.route("/coach")
def coach():

    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row

    rows=conn.execute("""

        SELECT clients.full_name

        FROM attendance

        JOIN clients ON attendance.client_id=clients.id

        WHERE attendance.session_date=DATE('now')

        ORDER BY clients.full_name

    """).fetchall()

    conn.close()

    html="""

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

    return render_template_string(html,rows=rows)


# ---------------- COACH BULK ATTENDANCE ----------------

@app.route("/coach_checkin",methods=["GET","POST"])
def coach_checkin():

    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row

    clients=conn.execute("""

        SELECT id,full_name

        FROM clients

        ORDER BY full_name

    """).fetchall()

    conn.close()

    if request.method=="POST":

        today=datetime.today().date().isoformat()

        challenge_id=get_active_challenge()

        selected=request.form.getlist("client")

        conn=sqlite3.connect(DB_PATH)

        for cid in selected:

            existing=conn.execute("""

                SELECT id

                FROM attendance

                WHERE client_id=? AND session_date=?

            """,(cid,today)).fetchone()

            if not existing:

                conn.execute("""

                    INSERT INTO attendance
                    (client_id,challenge_id,session_date)

                    VALUES (?,?,?)

                """,(cid,challenge_id,today))

        conn.commit()
        conn.close()

        return "✅ Attendance saved"


    html="""

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

    return render_template_string(html,clients=clients)


# ---------------- CHALLENGE BOARD ----------------

@app.route("/challenge_board",methods=["GET","POST"])
def challenge_board():

    challenge_dates=[

        "2026-03-10","2026-03-12",
        "2026-03-17","2026-03-19",
        "2026-03-24","2026-03-26",
        "2026-03-31","2026-04-02",
        "2026-04-07","2026-04-09",
        "2026-04-14","2026-04-16"

    ]

    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row

    clients=conn.execute("""

        SELECT id,full_name

        FROM clients

        ORDER BY full_name

    """).fetchall()

    attendance=conn.execute("""

        SELECT client_id,session_date

        FROM attendance

    """).fetchall()

    conn.close()

    lookup={(a["client_id"],a["session_date"]) for a in attendance}


    if request.method=="POST":

        client_id=request.form["client_id"]
        date=request.form["date"]

        conn=sqlite3.connect(DB_PATH)

        existing=conn.execute("""

            SELECT id FROM attendance

            WHERE client_id=? AND session_date=?

        """,(client_id,date)).fetchone()

        if existing:

            conn.execute("""

                DELETE FROM attendance

                WHERE client_id=? AND session_date=?

            """,(client_id,date))

        else:

            conn.execute("""

                INSERT INTO attendance
                (client_id,challenge_id,session_date)

                VALUES (?,1,?)

            """,(client_id,date))

        conn.commit()
        conn.close()

        return "Updated"


    html="""

    <h1>TSHRT 6 Week Challenge Attendance</h1>

    <style>

    table{border-collapse:collapse}

    td,th{padding:8px;border:1px solid #ccc;text-align:center}

    .present{background:#5cb85c;color:white;font-weight:bold}

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

        {% set key=(c['id'],d) %}

        <td>

        <form method="post">

        <input type="hidden" name="client_id" value="{{c['id']}}">

        <input type="hidden" name="date" value="{{d}}">

        <button class="{% if key in lookup %}present{% endif %}">

        {% if key in lookup %}✔{% else %}⬜{% endif %}

        </button>

        </form>

        </td>

        {% endfor %}

    </tr>

    {% endfor %}

    </table>

    """

    return render_template_string(html,clients=clients,dates=challenge_dates,lookup=lookup)


# ---------------- ROSTER SYNC ----------------

@app.route("/upload_roster",methods=["POST"])
def upload_roster():

    data=request.get_json()

    clients=data.get("clients",[])

    conn=sqlite3.connect(DB_PATH)

    conn.execute("DELETE FROM clients")

    for c in clients:

        conn.execute("""

            INSERT INTO clients (id,full_name)

            VALUES (?,?)

        """,(c["id"],c["full_name"]))

    conn.commit()
    conn.close()

    return "Roster uploaded successfully"


init_db()


# ---------------- SERVER START ----------------

if __name__=="__main__":

    port=int(os.environ.get("PORT",10000))

    app.run(host="0.0.0.0",port=port)
