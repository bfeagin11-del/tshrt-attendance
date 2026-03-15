import sqlite3
from flask import Flask, render_template_string, request, redirect, url_for
import os
from datetime import date

DB_PATH = "tshrt.db"

app = Flask(__name__)

# ---------------- DATABASE ----------------

def init_db():

```
conn = sqlite3.connect(DB_PATH)

conn.execute("""
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

conn.execute("""
CREATE TABLE IF NOT EXISTS finalized_dates (
    session_date TEXT PRIMARY KEY
)
""")

conn.commit()
conn.close()
```

def get_clients():

```
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, full_name
    FROM clients
    ORDER BY full_name
""").fetchall()

conn.close()
return rows
```

def get_attendance_lookup():

```
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT client_id, session_date
    FROM attendance
""").fetchall()

conn.close()

return {(r["client_id"], r["session_date"]) for r in rows}
```

def get_finalized_dates():

```
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT session_date
    FROM finalized_dates
""").fetchall()

conn.close()

return {r["session_date"] for r in rows}
```

def is_future_date(date_str):

```
return date_str > date.today().isoformat()
```

# ---------------- CHALLENGE BOARD ----------------

@app.route("/challenge_board", methods=["GET","POST"])
def challenge_board():

```
dates = [
    "2026-03-10","2026-03-12",
    "2026-03-17","2026-03-19",
    "2026-03-24","2026-03-26",
    "2026-03-31","2026-04-02",
    "2026-04-07","2026-04-09",
    "2026-04-14","2026-04-16"
]

if request.method == "POST":

    action = request.form.get("action")

    if action == "save_board":

        conn = sqlite3.connect(DB_PATH)
        finalized = get_finalized_dates()

        for d in dates:
            if d not in finalized:
                conn.execute("DELETE FROM attendance WHERE session_date=?", (d,))

        for key in request.form:

            if "|" not in key:
                continue

            cid, d = key.split("|")

            if d in finalized:
                continue

            conn.execute(
                "INSERT INTO attendance (client_id, session_date) VALUES (?,?)",
                (cid, d)
            )

        conn.commit()
        conn.close()

        return redirect(url_for("challenge_board"))

    if action == "finalize_date":

        selected = request.form.get("finalize_date")

        conn = sqlite3.connect(DB_PATH)

        conn.execute(
            "INSERT OR IGNORE INTO finalized_dates (session_date) VALUES (?)",
            (selected,)
        )

        conn.commit()
        conn.close()

        return redirect(url_for("challenge_board"))


clients = get_clients()
lookup = get_attendance_lookup()
finalized_dates = get_finalized_dates()

totals = {}

for c in clients:

    totals[c["id"]] = sum(
        1 for d in dates if (c["id"], d) in lookup
    )

html = """
```

<h1>TSHRT Challenge Attendance</h1>

<form method="post">

<input type="hidden" name="action" value="save_board">

<table border="1" cellpadding="6">

<tr>
<th>Client</th>

{% for d in dates %}

<th>{{d}}</th>
{% endfor %}

<th>Total</th>

</tr>

{% for c in clients %}

<tr>

<td>{{c['full_name']}}</td>

{% for d in dates %}

{% set key = c['id'] ~ "|" ~ d %}

<td>

<input type="checkbox"
name="{{key}}"

{% if (c['id'],d) in lookup %}
checked
{% endif %}

{% if d in finalized_dates %}
disabled
{% endif %}

>

</td>

{% endfor %}

<td>{{totals[c['id']]}} / 12</td>

</tr>

{% endfor %}

</table>

<br>

<button type="submit">Save Attendance</button>

</form>

<hr>

<form method="post">

<input type="hidden" name="action" value="finalize_date">

<select name="finalize_date">

{% for d in dates %}

<option value="{{d}}">{{d}}</option>
{% endfor %}

</select>

<button type="submit">Finalize Selected Class</button>

</form>

"""

```
return render_template_string(
    html,
    clients=clients,
    dates=dates,
    lookup=lookup,
    totals=totals,
    finalized_dates=finalized_dates
)
```

# ---------------- ROSTER SYNC ----------------

@app.route("/upload_roster", methods=["POST"])
def upload_roster():

```
try:

    data = request.get_json()

    clients = data.get("clients", [])

    conn = sqlite3.connect(DB_PATH)

    conn.execute("DELETE FROM clients")

    inserted = 0

    for c in clients:

    name = str(c.get("full_name") or c.get("name") or "").strip()

    if not name:
        continue

        conn.execute(
            "INSERT INTO clients (full_name) VALUES (?)",
            (name,)
        )

        inserted += 1

    conn.commit()
    conn.close()

    return f"Roster uploaded successfully ({inserted} clients)"

except Exception as e:

    return f"Server error: {str(e)}", 500
```

# ---------------- START SERVER ----------------

init_db()

if **name** == "**main**":

```
port = int(os.environ.get("PORT",10000))

app.run(host="0.0.0.0", port=port)
```
