from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os, json

app = Flask(__name__)

DATA_FILE = "roster_data.json"
CHALLENGE_START = "2026-03-09"


# ================= LOAD / SAVE =================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"clients": [], "attendance": {}}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ================= HELPERS =================

def challenge_dates():
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    dates = []

    for i in range(42):
        d = start + timedelta(days=i)
        if d.weekday() in [0, 2]:
            dates.append(d.strftime("%Y-%m-%d"))

    return dates


def label(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b")


def attendance_count(data, cid):
    return sum(
        1 for d in data.get("attendance", {})
        if cid in data["attendance"].get(d, [])
    )


# ================= SYNC =================

@app.route("/api/roster/sync", methods=["POST"])
def sync():
    data = load_data()
    incoming = request.get_json()

    existing = {c["client_id"]: c for c in data.get("clients", [])}

    for c in incoming.get("clients", []):
        cid = c["client_id"]
        existing[cid] = {
            "client_id": cid,
            "display_name": c.get("display_name", ""),
            "snapshot_score": c.get("snapshot_score", 0)
        }

    data["clients"] = list(existing.values())
    save_data(data)

    return jsonify({"status": "ok"})


# ================= TOGGLE =================

@app.route("/api/toggle", methods=["POST"])
def toggle():
    data = load_data()

    cid = request.json["client_id"]
    date = request.json["date"]

    data.setdefault("attendance", {})
    data["attendance"].setdefault(date, [])

    if cid in data["attendance"][date]:
        data["attendance"][date].remove(cid)
    else:
        data["attendance"][date].append(cid)

    save_data(data)
    return jsonify({"status": "ok"})


# ================= CHECKIN =================

@app.route("/checkin")
def checkin():
    data = load_data()
    dates = challenge_dates()

    clients = sorted(data["clients"], key=lambda x: x["display_name"])

    html = "<h2>Attendance</h2><table border=1><tr><th>Name</th>"

    for d in dates:
        html += f"<th>{label(d)}</th>"

    html += "<th>Total</th></tr>"

    for c in clients:
        cid = c["client_id"]
        name = c["display_name"]

        html += f"<tr><td>{name}</td>"

        for d in dates:
            present = cid in data.get("attendance", {}).get(d, [])
            color = "background:green" if present else ""

            html += f"<td onclick=\"toggle('{cid}','{d}')\" style=\"cursor:pointer;{color}\"></td>"

        total = attendance_count(data, cid)
        html += f"<td>{total}</td></tr>"

    html += """
    </table>
    <script>
    function toggle(cid,date){
        fetch("/api/toggle",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({client_id:cid,date:date})
        }).then(()=>location.reload());
    }
    </script>
    """

    return html


# ================= BOARD (YOUR STYLE + FIXED) =================

@app.route("/board")
def board():
    data = load_data()

    rows = []

    for c in data["clients"]:
        cid = c["client_id"]
        name = c["display_name"]

        attendance = attendance_count(data, cid)
        score = int(c.get("snapshot_score", 0))

        total = score + attendance

        rows.append({"name": name, "total": total})

    rows.sort(key=lambda x: -x["total"])

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
        font-size:56px;
        color:#FFD700;
        margin:20px;
        font-weight:bold;
    }

    .row {
        font-size:30px;
        width:900px;
        margin:12px auto;
        padding:12px;
        border-bottom:1px solid #444;
        text-align:left;
    }

    .rank {
        display:inline-block;
        width:80px;
        color:#FFD700;
        font-weight:bold;
    }

    .name {
        display:inline-block;
        width:450px;
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
            <span class="name">{r['name']}</span>
            <span class="points">{r['total']} pts</span>
        </div>
        """

    html += "</body></html>"
    return html


# ================= RUN =================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
