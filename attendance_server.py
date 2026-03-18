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
        "attendance": {},
        "challenge_points": {},
        "lifetime_points": {}
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

    for c in DATA["clients"]:
        cid = c["client_id"]

        if cid not in DATA["challenge_points"]:
            DATA["challenge_points"][cid] = 0

        if cid not in DATA["lifetime_points"]:
            DATA["lifetime_points"][cid] = 0

    save_data(DATA)
    return jsonify({"status": "success"})


# =========================
# CHECK-IN (AUTO POINTS)
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
        # REMOVE
        DATA["attendance"][date].remove(cid)

        DATA["challenge_points"][cid] = max(0, DATA["challenge_points"].get(cid, 0) - 1)
        DATA["lifetime_points"][cid] = max(0, DATA["lifetime_points"].get(cid, 0) - 1)

        status = "removed"
    else:
        # ADD
        DATA["attendance"][date].append(cid)

        DATA["challenge_points"][cid] = DATA["challenge_points"].get(cid, 0) + 1
        DATA["lifetime_points"][cid] = DATA["lifetime_points"].get(cid, 0) + 1

        status = "added"

    save_data(DATA)
    return jsonify({"status": status})


# =========================
# LEADERBOARD
# =========================
@app.route("/leaderboard")
def leaderboard():

    clients = DATA["clients"]

    board = []

    for c in clients:
        cid = c["client_id"]

        board.append({
            "name": c["display_name"],
            "challenge": DATA["challenge_points"].get(cid, 0),
            "lifetime": DATA["lifetime_points"].get(cid, 0)
        })

    # Sort by challenge points
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
        font-size:20px;
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
# CHECK-IN PAGE (UNCHANGED CORE)
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


@app.route("/api/attendance/<date>")
def get_attendance(date):
    return jsonify({
        "attendance": DATA["attendance"].get(date, [])
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
