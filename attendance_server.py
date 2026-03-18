from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import json

app = Flask(__name__)

DATA_FILE = "roster_data.json"

CHALLENGE_START = "2026-03-10"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "clients": [],
        "attendance": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

DATA = load_data()


# =========================
# ROSTER SYNC
# =========================
@app.route("/api/roster/sync", methods=["POST"])
def roster_sync():
    global DATA
    incoming = request.get_json()

    DATA["clients"] = incoming.get("clients", [])

    save_data(DATA)
    return jsonify({"status": "success"})


# =========================
# CHECK-IN (NO STORED POINTS)
# =========================
@app.route("/api/checkin", methods=["POST"])
def checkin():
    global DATA
    data = request.get_json()

    cid = data["client_id"]
    date = data["date"]

    if date not in DATA["attendance"]:
        DATA["attendance"][date] = []

    if cid in DATA["attendance"][date]:
        DATA["attendance"][date].remove(cid)
        status = "removed"
    else:
        DATA["attendance"][date].append(cid)
        status = "added"

    save_data(DATA)
    return jsonify({"status": status})


# =========================
# GET ATTENDANCE
# =========================
@app.route("/api/attendance/<date>")
def get_attendance(date):
    return jsonify({
        "attendance": DATA["attendance"].get(date, [])
    })


# =========================
# LEADERBOARD (CALCULATED)
# =========================
@app.route("/leaderboard")
def leaderboard():

    clients = DATA["clients"]
    attendance = DATA["attendance"]

    challenge_start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    challenge_end = challenge_start + timedelta(days=42)

    board = []

    for c in clients:
        cid = c["client_id"]

        challenge_points = 0
        lifetime_points = 0

        for date_str, attendees in attendance.items():
            if cid in attendees:
                lifetime_points += 1

                d = datetime.strptime(date_str, "%Y-%m-%d")
                if challenge_start <= d <= challenge_end:
                    challenge_points += 1

        board.append({
            "name": c["display_name"],
            "challenge": challenge_points,
            "lifetime": lifetime_points
        })

    board.sort(key=lambda x: x["challenge"], reverse=True)

    html = """
    <html>
    <head>
    <style>
    body { font-family: Arial; text-align:center; }

    .row {
        margin:6px;
        padding:10px;
        border:1px solid #333;
        width:400px;
        margin-left:auto;
        margin-right:auto;
    }

    .header {
        font-weight:bold;
        font-size:24px;
        margin-bottom:20px;
    }
    </style>
    </head>
    <body>

    <div class="header">CHALLENGE LEADERBOARD</div>
    """

    rank = 1

    for r in board:
        html += f"""
        <div class="row">
            #{rank} — {r['name']}<br>
            Challenge: {r['challenge']} | Lifetime: {r['lifetime']}
        </div>
        """
        rank += 1

    html += "</body></html>"

    return html


# =========================
# CHECK-IN PAGE
# =========================
@app.route("/checkin")
def checkin_page():

    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(42)]

    html = f"""
    <html>
    <head>
    <style>
    body {{ font-family: Arial; text-align:center; }}

    .date {{
        display:inline-block;
        padding:8px;
        margin:4px;
        border:1px solid #333;
        cursor:pointer;
    }}

    .active {{ background:#333; color:white; }}

    .client {{
        display:inline-block;
        width:200px;
        margin:6px;
        padding:10px;
        border:1px solid #333;
        cursor:pointer;
        background:#eee;
    }}

    .checked {{ background:green; color:white; }}
    </style>
    </head>
    <body>

    <h2>Attendance Board</h2>

    <div id="dates">
    """

    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        label = dt.strftime("%a %d %b")
        html += f'<div class="date" onclick="selectDate(\'{d}\')" id="d_{d}">{label}</div>'

    html += """
    </div>

    <h3 id="currentDate"></h3>
    <h4 id="count"></h4>

    <div id="clients"></div>

    <script>
    let clients = """ + json.dumps(DATA["clients"]) + """;
    let currentDate = "";

    function selectDate(date){
        currentDate = date;

        document.querySelectorAll('.date').forEach(el => el.classList.remove('active'));
        document.getElementById("d_" + date).classList.add("active");

        document.getElementById("currentDate").innerText = date;

        loadAttendance();
    }

    function loadAttendance(){
        fetch("/api/attendance/" + currentDate)
        .then(r=>r.json())
        .then(data=>{
            let present = data.attendance;

            let html = "";
            let count = 0;

            clients.forEach(c=>{
                let checked = present.includes(c.client_id);
                if(checked) count++;

                html += `
                <div class="client ${checked ? 'checked' : ''}"
                    onclick="toggle('${c.client_id}')">
                    ${c.display_name}
                </div>`;
            });

            document.getElementById("clients").innerHTML = html;
            document.getElementById("count").innerText =
                "Attendance: " + count + " / " + clients.length;
        });
    }

    function toggle(cid){
        fetch("/api/checkin", {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({
                client_id: cid,
                date: currentDate
            })
        })
        .then(()=>loadAttendance());
    }

    let today = new Date().toISOString().split('T')[0];
    selectDate(today);
    </script>

    </body>
    </html>
    """

    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
