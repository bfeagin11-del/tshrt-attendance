from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import json

app = Flask(__name__)

DATA_FILE = os.path.join(os.getcwd(), "roster_data.json")
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
    return [
        (start + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(DAYS)
        if (start + timedelta(days=i)).weekday() in [0, 2]
    ]


def label(d):
    return datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b")


def get_attendance_count(cid):
    DATA_LOCAL = load_data()
    count = 0
    for date in DATA_LOCAL.get("attendance", {}):
        if cid in DATA_LOCAL["attendance"][date]:
            count += 1
    return count


# ==============================
# SAFE SYNC (FIXED)
# ==============================

@app.route("/api/roster/sync", methods=["POST"])
def sync():
    global DATA
    incoming = request.get_json()

    DATA = load_data()  # 🔥 load existing

    existing_clients = {c["client_id"]: c for c in DATA.get("clients", [])}

    for c in incoming.get("clients", []):
        cid = c.get("client_id")
        if not cid:
            continue

        existing_clients[cid] = {
            "client_id": cid,
            "display_name": c.get("display_name", ""),
            "snapshot_score": c.get("snapshot_score", 0),
            "baseline_score": c.get("baseline_score", 0),
        }

    DATA["clients"] = list(existing_clients.values())

    save_data()

    return jsonify({"status": "success", "count": len(DATA["clients"])})


# ==============================
# TOGGLE ATTENDANCE
# ==============================

@app.route("/api/toggle", methods=["POST"])
def toggle():
    global DATA
    DATA = load_data()

    cid = request.json["client_id"]
    date = request.json["date"]

    DATA.setdefault("attendance", {})
    DATA["attendance"].setdefault(date, [])

    if cid in DATA["attendance"][date]:
        DATA["attendance"][date].remove(cid)
    else:
        DATA["attendance"][date].append(cid)

    save_data()
    return jsonify({"status": "ok"})


# ==============================
# GRID
# ==============================

@app.route("/checkin")
def grid():
    global DATA
    DATA = load_data()

    dates = get_dates()
    clients = DATA["clients"]

    html = "<table border=1><tr><th>Name</th>"

    for d in dates:
        html += f"<th>{label(d)}</th>"

    html += "<th>Total</th></tr>"

    for c in clients:
        cid = c["client_id"]
        name = c["display_name"]

        html += f"<tr><td>{name}</td>"

        for d in dates:
            checked = cid in DATA["attendance"].get(d, [])
            cls = "background:green" if checked else ""

            html += f"""
            <td onclick="toggle('{cid}','{d}',this)" style="cursor:pointer;{cls}">✔</td>
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
        }).then(()=>location.reload());
    }
    </script>
    """

    return html


# ==============================
# LEADERBOARD (FINAL)
# ==============================

@app.route("/board")
def board():
    DATA_LOCAL = load_data()

    rows = []

    for c in DATA_LOCAL.get("clients", []):
        cid = c["client_id"]
        name = c["display_name"]

        attendance = get_attendance_count(cid)
        score = c.get("snapshot_score", 0)

        total = score + attendance

        rows.append((name, total))

    rows.sort(key=lambda x: -x[1])

    html = "<h1>Leaderboard</h1>"

    for i, r in enumerate(rows, 1):
        html += f"<div>#{i} {r[0]} - {r[1]}</div>"

    return html


# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
