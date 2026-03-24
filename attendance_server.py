from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import json

app = Flask(__name__)

DATA_FILE = "roster_data.json"
CHALLENGE_START = "2026-03-09"
DAYS = 42


# ==============================
# LOAD / SAVE
# ==============================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"clients": [], "attendance": {}}


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(DATA, f, indent=2)


DATA = load_data()


# ==============================
# HELPERS
# ==============================

def get_dates():
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    dates = []

    for i in range(DAYS):
        d = start + timedelta(days=i)
        if d.weekday() in [0, 2]:  # Mon/Wed
            dates.append(d.strftime("%Y-%m-%d"))

    return dates


def label(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b")


def get_attendance_count(cid):
    count = 0
    for d in DATA["attendance"]:
        if cid in DATA["attendance"][d]:
            count += 1
    return count


# ==============================
# SYNC CLIENTS
# ==============================

@app.route("/api/roster/sync", methods=["POST"])
def sync():
    payload = request.get_json()
    DATA["clients"] = payload.get("clients", [])
    save_data()
    return jsonify({"status": "ok"})


# ==============================
# TOGGLE CHECK
# ==============================

@app.route("/api/toggle", methods=["POST"])
def toggle():
    cid = request.json["client_id"]
    date = request.json["date"]

    DATA["attendance"].setdefault(date, [])

    if cid in DATA["attendance"][date]:
        DATA["attendance"][date].remove(cid)
    else:
        DATA["attendance"][date].append(cid)

    save_data()
    return jsonify({"status": "ok"})


# ==============================
# GRID PAGE
# ==============================

@app.route("/checkin")
def grid():

    dates = get_dates()
    clients = DATA["clients"]

    html = """
    <html>
    <head>
    <style>
    body { font-family: Arial; }
    table { border-collapse: collapse; margin:auto; }
    td, th {
        border:1px solid #999;
        padding:6px;
        text-align:center;
    }
    th { background:#eee; }
    .box {
        width:20px;
        height:20px;
        border:1px solid #333;
        cursor:pointer;
    }
    .on { background:green; }
    </style>
    </head>
    <body>

    <h2 style="text-align:center;">TSHRT Attendance Grid</h2>

    <table>
    <tr>
        <th>Name</th>
    """

    for d in dates:
        html += f"<th>{label(d)}</th>"

    html += "<th>Total</th></tr>"

    for c in clients:
        cid = c["client_id"]
        name = c["display_name"]

        html += f"<tr><td>{name}</td>"

        for d in dates:
            checked = cid in DATA["attendance"].get(d, [])
            cls = "box on" if checked else "box"

            html += f"""
            <td>
            <div class="{cls}" onclick="toggle('{cid}','{d}',this)"></div>
            </td>
            """

        total = get_attendance_count(cid)
        html += f"<td>{total}</td></tr>"

    html += """
    </table>

    <script>
    function toggle(cid,date,el){
    fetch("/api/toggle",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({client_id:cid,date:date})
    }).then(()=>{
        el.classList.toggle("on");

        // update total
        let row = el.parentElement.parentElement;
        let boxes = row.querySelectorAll(".box.on");
        row.lastElementChild.innerText = boxes.length;
    });
}
    </script>

    </body>
    </html>
    """

    return html


# ==============================
# LEADERBOARD (simple for now)
# ==============================

@app.route("/board")
def board():
    rows = []

    for c in DATA["clients"]:
        cid = c["client_id"]
        name = c["display_name"]

        attendance = get_attendance_count(cid)

        rows.append({
            "name": name,
            "attendance": attendance,
            "points": attendance  # 1 per check
        })

    rows.sort(key=lambda x: -x["points"])

    html = """
    <html>
    <head>
    <style>
    body {
        background:black;
        color:white;
        font-family:Arial;
        text-align:center;
    }
    .title {
        font-size:48px;
        margin:20px;
        color:#FFD700;
    }
    .row {
        font-size:28px;
        padding:12px;
        margin:6px auto;
        width:600px;
        border-bottom:1px solid #444;
    }
    .rank {
        color:#FFD700;
        font-weight:bold;
    }
    .points {
        float:right;
    }
    </style>
    </head>
    <body>

    <div class="title">🔥 CHALLENGE LEADERBOARD 🔥</div>
    """

    for i, r in enumerate(rows, 1):
        html += f"""
        <div class="row">
            <span class="rank">#{i}</span>
            {r['name']}
            <span class="points">{r['points']} pts</span>
        </div>
        """

    html += "</body></html>"
    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
