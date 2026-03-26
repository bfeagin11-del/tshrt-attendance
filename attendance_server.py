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
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "clients": [],
        "attendance": {}
    }


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
        if d.weekday() in [0, 2]:  # Monday / Wednesday
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


@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    data = load_data()
    incoming = request.get_json(silent=True) or {}

    # Build existing client map
    existing = {c["client_id"]: c for c in data.get("clients", [])}

    for c in incoming.get("clients", []):

        cid = str(c.get("client_id", "")).strip()
        if not cid:
            continue

        # Get existing client OR create new one
        existing_client = existing.get(cid, {
            "client_id": cid,
            "display_name": "",
            "baseline_score": 0,
            "snapshot_score": 0,
            "attendance_count": 0
        })

        # Update name safely
        existing_client["display_name"] = str(
            c.get("display_name", existing_client.get("display_name", ""))
        ).strip()

        # 🔥 ONLY update scores if present (prevents wipe/reset)
        if "baseline_score" in c:
            existing_client["baseline_score"] = safe_int(c.get("baseline_score", 0))

        if "snapshot_score" in c:
            existing_client["snapshot_score"] = safe_int(c.get("snapshot_score", 0))

        # Preserve attendance
        existing_client["attendance_count"] = existing_client.get("attendance_count", 0)

        # Save back
        existing[cid] = existing_client

    # Save full updated roster
    data["clients"] = list(existing.values())
    save_data(data)

    return jsonify({
        "status": "success",
        "count": len(data["clients"])
    })


@app.route("/api/toggle", methods=["POST"])
def toggle():
    data = load_data()
    payload = request.get_json(silent=True) or {}

    cid = str(payload.get("client_id", "")).strip()
    date_str = str(payload.get("date", "")).strip()

    if not cid or not date_str:
        return jsonify({"status": "error", "message": "client_id and date required"}), 400

    data.setdefault("attendance", {})
    data["attendance"].setdefault(date_str, [])

    if cid in data["attendance"][date_str]:
        data["attendance"][date_str].remove(cid)
    else:
        data["attendance"][date_str].append(cid)

    save_data(data)
    return jsonify({"status": "ok"})


@app.route("/checkin")
def checkin():
    data = load_data()
    dates = get_dates()
    clients = sorted(data.get("clients", []), key=sort_last_name)

    html = """
    <html>
    <head>
    <title>TSHRT Attendance</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f5f5f5;
            margin: 20px;
        }
        h2 {
            text-align: center;
            margin-bottom: 20px;
        }
        table {
            border-collapse: collapse;
            margin: auto;
            background: white;
        }
        th, td {
            border: 1px solid #999;
            padding: 8px;
            text-align: center;
            min-width: 52px;
        }
        th.name-col, td.name-col {
            text-align: left;
            min-width: 220px;
            padding-left: 10px;
        }
        th {
            background: #ececec;
            font-weight: bold;
        }
        td.box {
            cursor: pointer;
            background: white;
            font-size: 22px;
            line-height: 1;
        }
        td.on {
            background: green;
            color: black;
            font-weight: bold;
        }
        td.total {
            font-weight: bold;
            min-width: 60px;
        }
    </style>
    </head>
    <body>
    <h2>TSHRT Attendance Grid</h2>
    <table>
        <tr>
            <th class="name-col">Name</th>
    """

    for d in dates:
        html += f"<th>{label(d)}</th>"

    html += "<th>Total</th></tr>"

    for c in clients:
        cid = c["client_id"]
        name = c.get("display_name", "")
        html += f"<tr><td class='name-col'>{name}</td>"

        for d in dates:
            present = cid in data.get("attendance", {}).get(d, [])
            cls = "box on" if present else "box"
            mark = "✓" if present else ""
            html += (
                f"<td class='{cls}' onclick=\"toggleBox('{cid}','{d}', this)\">{mark}</td>"
            )

        total = attendance_count(data, cid)
        html += f"<td class='total'>{total}</td></tr>"

    html += """
    </table>

    <script>
    function toggleBox(cid, dateStr, el) {
        fetch("/api/toggle", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({client_id: cid, date: dateStr})
        }).then(() => {
            if (el.classList.contains("on")) {
                el.classList.remove("on");
                el.innerText = "";
            } else {
                el.classList.add("on");
                el.innerText = "✓";
            }

            const row = el.parentElement;
            const checked = row.querySelectorAll("td.box.on").length;
            row.querySelector("td.total").innerText = checked;
        });
    }
    </script>
    </body>
    </html>
    """

    return html


@app.route("/board")
def board():
    data = load_data()

    rows = []
    for c in data.get("clients", []):
        cid = c["client_id"]
        name = c.get("display_name", "")
        attendance = attendance_count(data, cid)
        snapshot_score = safe_int(c.get("snapshot_score", 0))
        baseline_score = safe_int(c.get("baseline_score", 0))

        current_total = snapshot_score + attendance
        lifetime_total = baseline_score + snapshot_score + attendance

        rows.append({
            "name": name,
            "current_total": current_total,
            "lifetime_total": lifetime_total,
            "attendance": attendance
        })

    rows.sort(key=lambda r: (-r["current_total"], r["name"].lower()))

    html = """
    <html>
    <head>
    <title>TSHRT Challenge Board</title>
    <style>
    body {
        background: black;
        color: white;
        font-family: Arial, sans-serif;
        text-align: center;
        margin: 0;
        padding: 20px;
    }
    .title {
        font-size: 56px;
        color: #FFD700;
        margin: 20px;
        font-weight: bold;
    }
    .subtitle {
        font-size: 24px;
        color: #cccccc;
        margin-bottom: 25px;
    }
    .row {
        font-size: 30px;
        width: 980px;
        margin: 12px auto;
        padding: 12px;
        border-bottom: 1px solid #444;
        text-align: left;
    }
    .rank {
        display: inline-block;
        width: 80px;
        color: #FFD700;
        font-weight: bold;
    }
    .name {
        display: inline-block;
        width: 360px;
    }
    .points {
        float: right;
    }
    </style>
    </head>
    <body>
        <div class="title">🔥 CHALLENGE LEADERBOARD 🔥</div>
        <div class="subtitle">Current Challenge + Lifetime Progress</div>
    """

    for i, r in enumerate(rows, 1):
        html += f"""
        <div class="row">
            <span class="rank">#{i}</span>
            <span class="name">{r['name']}</span>
            <span class="points">C:{r['current_total']} | L:{r['lifetime_total']}</span>
        </div>
        """

    html += "</body></html>"
    return html


@app.route("/leaderboard")
def leaderboard():
    data = load_data()

    rows = []
    for c in data.get("clients", []):
        cid = c["client_id"]
        name = c.get("display_name", "")
        attendance = attendance_count(data, cid)
        snapshot_score = safe_int(c.get("snapshot_score", 0))
        baseline_score = safe_int(c.get("baseline_score", 0))

        current_total = snapshot_score + attendance
        lifetime_total = baseline_score + snapshot_score + attendance

        rows.append({
            "name": name,
            "current_total": current_total,
            "lifetime_total": lifetime_total,
            "attendance": attendance
        })

    rows.sort(key=lambda r: (-r["lifetime_total"], r["name"].lower()))

    html = """
    <html>
    <head>
    <title>TSHRT Lifetime Leaderboard</title>
    <style>
    body {
        background: black;
        color: white;
        font-family: Arial, sans-serif;
        text-align: center;
        margin: 0;
        padding: 20px;
    }
    .title {
        font-size: 52px;
        color: #FFD700;
        margin: 20px;
        font-weight: bold;
    }
    .subtitle {
        font-size: 22px;
        color: #cccccc;
        margin-bottom: 25px;
    }
    .row {
        font-size: 28px;
        width: 980px;
        margin: 12px auto;
        padding: 12px;
        border-bottom: 1px solid #444;
        text-align: left;
    }
    .rank {
        display: inline-block;
        width: 80px;
        color: #FFD700;
        font-weight: bold;
    }
    .name {
        display: inline-block;
        width: 360px;
    }
    .points {
        float: right;
    }
    </style>
    </head>
    <body>
        <div class="title">🔥 LIFETIME LEADERBOARD 🔥</div>
        <div class="subtitle">Baseline + Current Score + Attendance</div>
    """

    for i, r in enumerate(rows, 1):
        html += f"""
        <div class="row">
            <span class="rank">#{i}</span>
            <span class="name">{r['name']}</span>
            <span class="points">L:{r['lifetime_total']} | C:{r['current_total']}</span>
        </div>
        """

    html += "</body></html>"
    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
