import sqlite3
from flask import Flask, render_template_string, request, redirect, url_for
import os
from datetime import date

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

    conn.execute("""
    CREATE TABLE IF NOT EXISTS finalized_dates (
        session_date TEXT PRIMARY KEY
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


def get_attendance_lookup():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT client_id, session_date
        FROM attendance
    """).fetchall()
    conn.close()
    return {(r["client_id"], r["session_date"]) for r in rows}


def get_finalized_dates():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT session_date
        FROM finalized_dates
    """).fetchall()
    conn.close()
    return {r["session_date"] for r in rows}


def is_future_date(date_str: str) -> bool:
    return date_str > date.today().isoformat()


# ---------------- HOME ----------------

@app.route("/")
def home():
    return """
    <h1>TSHRT Attendance</h1>
    <p><a href="/challenge_board">Challenge Attendance Board</a></p>
    """


# ---------------- CHALLENGE BOARD ----------------

@app.route("/challenge_board", methods=["GET", "POST"])
def challenge_board():
    dates = [
        "2026-03-10", "2026-03-12",
        "2026-03-17", "2026-03-19",
        "2026-03-24", "2026-03-26",
        "2026-03-31", "2026-04-02",
        "2026-04-07", "2026-04-09",
        "2026-04-14", "2026-04-16"
    ]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "save_board":
            conn = sqlite3.connect(DB_PATH)
            finalized = get_finalized_dates()

            # only clear non-finalized dates
            for d in dates:
                if d not in finalized:
                    conn.execute("DELETE FROM attendance WHERE session_date = ?", (d,))

            # re-insert only checked boxes for non-finalized dates
            for key in request.form:
                if "|" not in key:
                    continue
                cid, d = key.split("|", 1)
                if d in finalized:
                    continue
                conn.execute("""
                    INSERT INTO attendance (client_id, session_date)
                    VALUES (?, ?)
                """, (cid, d))

            conn.commit()
            conn.close()
            return redirect(url_for("challenge_board"))

        if action == "finalize_date":
            selected_date = request.form.get("finalize_date", "").strip()
            if selected_date in dates:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("""
                    INSERT OR IGNORE INTO finalized_dates (session_date)
                    VALUES (?)
                """, (selected_date,))
                conn.commit()
                conn.close()
            return redirect(url_for("challenge_board"))

    clients = get_clients()
    lookup = get_attendance_lookup()
    finalized_dates = get_finalized_dates()

    date_labels = {
        "2026-03-10": "Mon 3/10",
        "2026-03-12": "Wed 3/12",
        "2026-03-17": "Mon 3/17",
        "2026-03-19": "Wed 3/19",
        "2026-03-24": "Mon 3/24",
        "2026-03-26": "Wed 3/26",
        "2026-03-31": "Mon 3/31",
        "2026-04-02": "Wed 4/2",
        "2026-04-07": "Mon 4/7",
        "2026-04-09": "Wed 4/9",
        "2026-04-14": "Mon 4/14",
        "2026-04-16": "Wed 4/16",
    }

    totals = {}
    for c in clients:
        count = sum(1 for d in dates if (c["id"], d) in lookup)
        totals[c["id"]] = count

    html = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>TSHRT Challenge Attendance</title>
<style>
body {
    font-family: Arial, Helvetica, sans-serif;
    margin: 16px;
}

h1 {
    margin-bottom: 8px;
}

.topbar {
    margin-bottom: 14px;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
}

.board-container {
    overflow: auto;
    border: 1px solid #ccc;
    max-width: 100%;
}

table {
    border-collapse: collapse;
    min-width: 1200px;
}

th, td {
    border: 1px solid #ccc;
    padding: 8px;
    text-align: center;
    background: white;
}

thead th {
    position: sticky;
    top: 0;
    background: #f0f0f0;
    z-index: 3;
}

thead th:first-child,
tbody td:first-child {
    position: sticky;
    left: 0;
    background: white;
    z-index: 4;
    text-align: left;
    font-weight: bold;
    min-width: 220px;
}

thead th:first-child {
    background: #f0f0f0;
}

thead th:last-child,
tbody td:last-child {
    position: sticky;
    right: 0;
    background: white;
    z-index: 4;
    font-weight: bold;
    min-width: 90px;
}

thead th:last-child {
    background: #f0f0f0;
}

.cell-wrap {
    display: flex;
    justify-content: center;
    align-items: center;
}

.cell-btn {
    width: 28px;
    height: 28px;
    border: 1px solid #aaa;
    border-radius: 6px;
    font-size: 16px;
    cursor: pointer;
    line-height: 26px;
    padding: 0;
}

.present {
    background: #5cb85c;
    color: white;
    border-color: #4b9d4b;
}

.open {
    background: white;
    color: #333;
}

.future {
    background: #ddd;
    color: #777;
    border-color: #ccc;
    cursor: not-allowed;
}

.locked {
    outline: 2px solid #666;
}

.legend {
    margin: 10px 0 14px 0;
}

.legend span {
    margin-right: 16px;
}

.save-row {
    margin-top: 14px;
}

button.main-btn, select {
    padding: 8px 12px;
    font-size: 14px;
}

.note {
    color: #555;
    margin-bottom: 10px;
}
</style>
</head>
<body>

<h1>TSHRT Challenge Attendance</h1>
<div class="note">Edit attendance on the board, then save. Finalize a class date only after you verify it for points.</div>

<div class="legend">
    <span>✔ Green = attended</span>
    <span>⬜ White = open</span>
    <span>⬛ Gray = future</span>
    <span>Border = finalized/locked</span>
</div>

<form method="post" class="topbar">
    <input type="hidden" name="action" value="finalize_date">
    <label for="finalize_date"><strong>Finalize Class Attendance:</strong></label>
    <select name="finalize_date" id="finalize_date">
        {% for d in dates %}
        <option value="{{ d }}">{{ date_labels[d] }}</option>
        {% endfor %}
    </select>
    <button class="main-btn" type="submit">Finalize Selected Class</button>
</form>

<form method="post">
    <input type="hidden" name="action" value="save_board">

    <div class="board-container">
        <table>
            <thead>
                <tr>
                    <th>Client</th>
                    {% for d in dates %}
                    <th>{{ date_labels[d] }}</th>
                    {% endfor %}
                    <th>Total</th>
                </tr>
            </thead>
            <tbody>
                {% for c in clients %}
                <tr>
                    <td>{{ c['full_name'] }}</td>

                    {% for d in dates %}
                    {% set key = c['id'] ~ "|" ~ d %}
                    {% set checked = (c['id'], d) in lookup %}
                    {% set locked = d in finalized_dates %}
                    {% set future = d in future_dates %}

                    <td>
                        <div class="cell-wrap">
                            {% if future %}
                                <button type="button" class="cell-btn future" disabled>⬛</button>
                            {% else %}
                                <label>
                                    <input
                                        type="checkbox"
                                        name="{{ key }}"
                                        value="1"
                                        {% if checked %}checked{% endif %}
                                        {% if locked %}disabled{% endif %}
                                        style="display:none;"
                                    >
                                    <span class="cell-btn {% if checked %}present{% else %}open{% endif %} {% if locked %}locked{% endif %}">
                                        {% if checked %}✔{% else %}⬜{% endif %}
                                    </span>
                                </label>
                            {% endif %}
                        </div>
                    </td>
                    {% endfor %}

                    <td>{{ totals[c['id']] }} / 12</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="save-row">
        <button class="main-btn" type="submit">Save Attendance</button>
    </div>
</form>

<script>
document.querySelectorAll('label').forEach(function(label) {
    label.addEventListener('click', function(e) {
        const checkbox = label.querySelector('input[type="checkbox"]');
        if (!checkbox || checkbox.disabled) return;

        e.preventDefault();
        checkbox.checked = !checkbox.checked;

        const span = label.querySelector('span');
        if (checkbox.checked) {
            span.textContent = '✔';
            span.classList.remove('open');
            span.classList.add('present');
        } else {
            span.textContent = '⬜';
            span.classList.remove('present');
            span.classList.add('open');
        }
    });
});
</script>

</body>
</html>
"""

    return render_template_string(
        html,
        clients=clients,
        dates=dates,
        date_labels=date_labels,
        lookup=lookup,
        totals=totals,
        finalized_dates=finalized_dates,
        future_dates={d for d in dates if is_future_date(d)},
    )


# ---------------- ROSTER SYNC ----------------

@app.route("/upload_roster", methods=["POST"])
def upload_roster():

    try:
        data = request.get_json()

        if not data or "clients" not in data:
            return "No client data received", 400

        clients = data["clients"]

        conn = sqlite3.connect(DB_PATH)

        conn.execute("DELETE FROM clients")

        inserted = 0

        for c in clients:

            cid = str(c.get("id", "")).strip()
            name = str(c.get("full_name", "")).strip()

            if not cid or not name:
                continue

            conn.execute(
                "INSERT INTO clients (id, full_name) VALUES (?, ?)",
                (cid, name)
            )

            inserted += 1

        conn.commit()
        conn.close()

        return f"Roster uploaded successfully ({inserted} clients)"

    except Exception as e:

        return f"Server error: {str(e)}", 500


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
