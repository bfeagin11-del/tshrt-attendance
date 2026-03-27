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


def label(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %d %b")


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


def sort_last_name(client):
    name = str(client.get("display_name", "")).strip()
    parts = name.split()
    return (parts[-1].lower() if parts else "", name.lower())


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

    existing = {}
    for c in data.get("clients", []):
        cid = str(c.get("client_id", "")).strip()
        if cid:
            existing[cid] = c

    for c in incoming.get("clients", []):
        cid = str(c.get("client_id", "")).strip()
        if not cid:
            continue

        existing_client = existing.get(cid, {
            "client_id": cid,
            "display_name": "",
            "baseline_score": 0,
            "snapshot_score": 0,
            "attendance_count": 0
        })

        existing_client["display_name"] = str(
            c.get("display_name", existing_client.get("display_name", ""))
        ).strip()

        if "baseline_score" in c:
            existing_client["baseline_score"] = safe_int(c.get("baseline_score", 0))

        if "snapshot_score" in c:
            existing_client["snapshot_score"] = safe_int(c.get("snapshot_score", 0))

        existing[cid] = existing_client

    data["clients"] = list(existing.values())
    save_data(data)

    return jsonify({"status": "success", "count": len(data["clients"])})


# ==============================
# ATTENDANCE
# ==============================

@app.route("/api/toggle", methods=["POST"])
def toggle():
    data = load_data()
    payload = request.get_json(silent=True) or {}

    cid = str(payload.get("client_id", "")).strip()
    date_str = str(payload.get("date", "")).strip()

    data.setdefault("attendance", {})
    data["attendance"].setdefault(date_str, [])

    if cid in data["attendance"][date_str]:
        data["attendance"][date_str].remove(cid)
    else:
        data["attendance"][date_str].append(cid)

    save_data(data)
    return jsonify({"status": "ok"})


# ==============================
# MAIN BOARD (UNCHANGED)
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

        current = snapshot + attendance
        lifetime = baseline + snapshot + attendance

        rows.append({
            "name": c.get("display_name", ""),
            "current": current,
            "lifetime": lifetime
        })

    rows.sort(key=lambda r: -r["current"])

    html = """
    <html>
    <head>
        <style>
            body { background:black; color:white; text-align:center; font-family:Arial; }
            h1 { color:gold; font-size:48px; margin-top:30px; }
            .row { font-size:26px; margin:10px auto; width:60%; padding:10px; border-bottom:1px solid gold; }
            .rank { color:gold; font-weight:bold; margin-right:15px; }
        </style>
    </head>
    <body>
        <h1>🔥 CHALLENGE LEADERBOARD 🔥</h1>
    """

    for i, r in enumerate(rows, 1):
        html += f'<div class="row"><span class="rank">#{i}</span> {r["name"]} &nbsp;&nbsp;&nbsp; C:{r["current"]} | L:{r["lifetime"]}</div>'

    html += "</body></html>"
    return html


# ==============================
# 🔥 NEW LEADERBOARD ROUTE (THIS WAS MISSING)
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
