from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import json

print("🔥🔥🔥 NEW VERSION LOADED 🔥🔥🔥")

app = Flask(__name__)

DATA_FILE = "roster_data.json"
CHALLENGE_START = "2026-03-09"
DAYS = 42


# ==============================
# LOAD / SAVE
# ==============================

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("clients", [])
                    data.setdefault("attendance", {})
                    return data
        except Exception:
            pass

    return {"clients": [], "attendance": {}}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ==============================
# HELPERS
# ==============================

def get_dates():
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    dates = []
    for i in range(DAYS):
        d = start + timedelta(days=i)
        if d.weekday() in [0, 2]:
            dates.append(d.strftime("%Y-%m-%d"))
    return dates


def attendance_count(data, cid):
    total = 0
    for date_str, attendees in data.get("attendance", {}).items():
        if cid in attendees:
            total += 1
    return total


def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(round(float(value)))
    except Exception:
        return default


# ==============================
# ROUTES
# ==============================

@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


@app.route("/debug/test")
def debug_test():
    return "DEBUG ROUTE ACTIVE"


@app.route("/debug/roster")
def debug_roster():
    data = load_data()
    return jsonify(data)


# ==============================
# SYNC
# ==============================

@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    data = load_data()
    incoming = request.get_json(silent=True) or {}

    new_clients = []

    for c in incoming.get("clients", []):

        name = str(c.get("name", "")).strip()
        if not name:
            continue

        # 🔥 CREATE ID FROM NAME
        client_id = name.replace(" ", "_").lower()

        snapshot = safe_int(c.get("snapshot", 0))
        lifetime = safe_int(c.get("lifetime", 0))

        new_clients.append({
            "client_id": client_id,
            "display_name": name,
            "snapshot_score": snapshot,
            "baseline_score": lifetime
        })

    data["clients"] = new_clients
    save_data(data)

    print("🔥 SAVED CLIENTS:", len(new_clients))

    return jsonify({
        "status": "success",
        "count": len(new_clients)
    })


# ==============================
# ATTENDANCE
# ==============================

@app.route("/api/toggle", methods=["POST"])
def toggle():
    data = load_data()
    payload = request.get_json(silent=True) or {}

    cid = str(payload.get("client_id", "")).strip()
    date_str = datetime.now().strftime("%Y-%m-%d")

    data.setdefault("attendance", {})
    data["attendance"].setdefault(date_str, [])

    if cid in data["attendance"][date_str]:
        data["attendance"][date_str].remove(cid)
    else:
        data["attendance"][date_str].append(cid)

    save_data(data)
    return jsonify({"status": "ok"})
@app.route("/api/toggle_date", methods=["POST"])
def toggle_date():
    data = load_data()
    payload = request.get_json()

    cid = payload["client_id"]
    date = payload["date"]

    data.setdefault("attendance", {})
    data["attendance"].setdefault(date, [])

    if cid in data["attendance"][date]:
        data["attendance"][date].remove(cid)
    else:
        data["attendance"][date].append(cid)

    save_data(data)
    return jsonify({"status": "ok"})

# ==============================
# 🔥 CHECK-IN PAGE (FIXES OPTION 7)
# ==============================

@app.route("/checkin")
def checkin():
    data = load_data()
    dates = get_dates()

    html = """
    <html>
    <head>
        <style>
            body { background:black; color:white; font-family:Arial; text-align:center; }
            h1 { color:gold; }

            table { margin:auto; border-collapse:collapse; }
            th, td {
                border:1px solid gold;
                padding:8px;
                font-size:14px;
            }

            th { color:gold; }

            .box {
                width:20px;
                height:20px;
                cursor:pointer;
                margin:auto;
            }

            .present { background:green; }
            .absent { background:white; }

        </style>
    </head>
    <body>

    <h1>🔥 ATTENDANCE BOARD 🔥</h1>

    <table>
        <tr>
            <th>Name</th>
    """

    # Header dates
    for d in dates:
        html += f"<th>{d[5:]}</th>"

    html += "</tr>"

    # Rows
    for c in data.get("clients", []):
        cid = c["client_id"]
        name = c["display_name"]

        html += f"<tr><td>{name}</td>"

        for d in dates:
            present = cid in data.get("attendance", {}).get(d, [])
            cls = "present" if present else "absent"

            html += f"""
            <td>
                <div class="box {cls}" onclick="toggle('{cid}', '{d}')"></div>
            </td>
            """

        html += "</tr>"

    html += """
    </table>

    <script>
    function toggle(cid, date){
        fetch('/api/toggle_date', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ client_id: cid, date: date })
        }).then(()=>location.reload());
    }
    </script>

    </body></html>
    """

    return html

# ==============================
# 🔥 DISPLAY BOARD (OPTION 9)
# ==============================

@app.route("/board")
def board():
    data = load_data()

    rows = []
    for c in data.get("clients", []):
        cid = c["client_id"]

        attendance = attendance_count(data, cid)
        snapshot = safe_int(c.get("snapshot_score", 0))
        baseline = safe_int(c.get("baseline_score", 0))

        current = snapshot + (attendance * 2)
        lifetime = baseline + (attendance * 2)

        rows.append((c.get("display_name", ""), current, lifetime))

    rows.sort(key=lambda r: -r[1])

    html = """
    <html>
    <head>
        <style>
            body { background:black; color:white; text-align:center; font-family:Arial; }
            h1 { color:gold; font-size:48px; }
            .row { font-size:26px; margin:10px; border-bottom:1px solid gold; padding:10px; }
        </style>
    </head>
    <body>
        <h1>🔥 CHALLENGE LEADERBOARD 🔥</h1>
    """

    for i, r in enumerate(rows, 1):
        html += f'<div class="row">#{i} {r[0]} | C:{r[1]} | L:{r[2]}</div>'

    html += "</body></html>"
    return html


# ==============================
# 🔥 LEADERBOARD (OPTION 8 FIX)
# ==============================

@app.route("/leaderboard")
def leaderboard():
    return board()


# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
