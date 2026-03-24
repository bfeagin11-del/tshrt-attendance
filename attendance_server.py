from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os
import json

app = Flask(__name__)

DATA_FILE = "roster_data.json"
CHALLENGE_START = "2026-03-09"


# ============================================================
# LOAD / SAVE
# ============================================================

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("clients", [])
    data.setdefault("attendance", {})
    data.setdefault("challenges", {})
    data["challenges"].setdefault("base", {})
    data["challenges"].setdefault("current", {})
    data["challenges"].setdefault("history", {})

    return data


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, indent=2)


DATA = load_data()


# ============================================================
# HELPERS
# ============================================================

def get_client_name(client):
    return str(client.get("display_name", "")).strip()


def get_client_id(client):
    return str(client.get("client_id", "")).strip()


def challenge_dates():
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(42)]


def date_label(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%a %d %b")
    except Exception:
        return date_str


def ensure_client_structures():
    for client in DATA.get("clients", []):
        cid = get_client_id(client)
        if cid:
            DATA["challenges"]["base"].setdefault(cid, 0)
            DATA["challenges"]["current"].setdefault(cid, 0)
            DATA["challenges"]["history"].setdefault(cid, [])


def recalc_scores():
    """
    base:
        attendance BEFORE challenge start

    current:
        attendance DURING challenge window,
        but ONLY Monday (0) and Wednesday (2)

    lifetime:
        base + sum(history) + current
        (calculated later in build_rows)
    """
    start = datetime.strptime(CHALLENGE_START, "%Y-%m-%d")
    end = start + timedelta(days=41)

    base_scores = {}
    current_scores = {}

    for client in DATA.get("clients", []):
        cid = get_client_id(client)
        if cid:
            base_scores[cid] = 0
            current_scores[cid] = 0

    for date_str, attendees in DATA.get("attendance", {}).items():
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue

        if not isinstance(attendees, list):
            continue

        for cid in attendees:
            if cid not in base_scores:
                continue

            if d < start:
                base_scores[cid] += 1
            elif start <= d <= end:
                if d.weekday() in [0, 2]:
                    current_scores[cid] += 1

    DATA["challenges"]["base"] = base_scores
    DATA["challenges"]["current"] = current_scores


def build_rows():
    rows = []

    for client in DATA.get("clients", []):
        cid = get_client_id(client)
        name = get_client_name(client)

        base_score = int(DATA["challenges"].get("base", {}).get(cid, 0))
        current_score = int(DATA["challenges"].get("current", {}).get(cid, 0))
        history_scores = DATA["challenges"].get("history", {}).get(cid, [])

        if not isinstance(history_scores, list):
            history_scores = []

        history_total = sum(int(x) for x in history_scores if isinstance(x, (int, float)))
        initial_score = int(client.get("snapshot_score", 0))
        lifetime_total = initial_score + current_score

        rows.append({
            "client_id": cid,
            "name": name,
            "base": base_score,
            "current": current_score,
            "history_total": history_total,
            "lifetime": lifetime_total,
            "history_list": history_scores,
        })

    rows.sort(key=lambda x: (-x["current"], -x["lifetime"], x["name"].lower()))
    return rows


ensure_client_structures()
recalc_scores()
save_data()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


# ============================================================
# SYNC CLIENT ROSTER
# ============================================================

@app.route("/api/roster/sync", methods=["POST"])
def sync_roster():
    incoming = request.get_json(silent=True) or {}
    clients = incoming.get("clients", [])

    if not isinstance(clients, list):
        return jsonify({"status": "error", "message": "clients must be a list"}), 400

    clean_clients = []
    seen = set()

    for client in clients:
        if not isinstance(client, dict):
            continue

        cid = str(client.get("client_id", "")).strip()
        name = str(client.get("display_name", "")).strip()

        if not cid or not name:
            continue

        if cid in seen:
            continue

        seen.add(cid)

        clean_clients.append({
            "client_id": cid,
            "display_name": name,
            "first_name": str(client.get("first_name", "")).strip(),
            "last_name": str(client.get("last_name", "")).strip(),
        })

    DATA["clients"] = clean_clients
    ensure_client_structures()
    recalc_scores()
    save_data()

    return jsonify({
        "status": "success",
        "count": len(clean_clients)
    })


# ============================================================
# ATTENDANCE API
# ============================================================

@app.route("/api/attendance/<date_str>")
def get_attendance(date_str):
    attendees = DATA.get("attendance", {}).get(date_str, [])
    if not isinstance(attendees, list):
        attendees = []

    return jsonify({
        "attendance": attendees,
        "total": len(attendees)
    })


@app.route("/api/checkin", methods=["POST"])
def toggle_checkin():
    payload = request.get_json(silent=True) or {}

    cid = str(payload.get("client_id", "")).strip()
    date_str = str(payload.get("date", "")).strip()

    if not cid or not date_str:
        return jsonify({"status": "error", "message": "client_id and date required"}), 400

    DATA.setdefault("attendance", {})
    DATA["attendance"].setdefault(date_str, [])

    attendees = DATA["attendance"][date_str]

    if cid in attendees:
        attendees.remove(cid)
        action = "removed"
    else:
        attendees.append(cid)
        action = "added"

    recalc_scores()
    save_data()

    return jsonify({"status": action})


# ============================================================
# LOCK CHALLENGE
# ============================================================

@app.route("/lock_challenge")
def lock_challenge():
    """
    Moves CURRENT challenge score into HISTORY and resets:
    - current challenge scores
    - attendance records

    base stays as historical pre-challenge attendance.
    """
    ensure_client_structures()
    recalc_scores()

    for cid, score in DATA["challenges"]["current"].items():
        if score > 0:
            DATA["challenges"]["history"].setdefault(cid, []).append(score)

    DATA["attendance"] = {}
    DATA["challenges"]["current"] = {cid: 0 for cid in DATA["challenges"]["current"].keys()}

    save_data()
    return "Challenge locked and current scores reset."


# ============================================================
# LEADERBOARD PAGE
# ============================================================

@app.route("/leaderboard")
def leaderboard():
    rows = build_rows()

    html = """
    <html>
    <head>
        <title>TSHRT Leaderboard</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #111;
                color: white;
                text-align: center;
                margin: 0;
                padding: 20px;
            }
            .title {
                font-size: 42px;
                font-weight: bold;
                margin-bottom: 10px;
                color: #FFD700;
            }
            .subtitle {
                font-size: 18px;
                color: #ccc;
                margin-bottom: 30px;
            }
            .row {
                width: 820px;
                margin: 10px auto;
                padding: 14px 18px;
                border: 1px solid #444;
                border-radius: 10px;
                background: #1e1e1e;
                font-size: 24px;
                text-align: left;
            }
            .rank {
                display: inline-block;
                width: 70px;
                color: #FFD700;
                font-weight: bold;
            }
            .name {
                display: inline-block;
                width: 340px;
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

    if not rows:
        html += '<div class="row">NO DATA FOUND</div>'
    else:
        rank = 1
        for row in rows:
            html += f"""
            <div class="row">
                <span class="rank">#{rank}</span>
                <span class="name">{row['name']}</span>
                <span class="points">C:{int(row['current'])} | L:{int(row['lifetime'])}</span>
            </div>
            """
            rank += 1

    html += """
    </body>
    </html>
    """
    return html


# ============================================================
# BIG DISPLAY BOARD
# ============================================================

@app.route("/board")
@app.route("/challenge_board")
def board():
    rows = build_rows()

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
                margin: 20px;
                color: #FFD700;
                font-weight: bold;
            }
            .subtitle {
                font-size: 24px;
                color: #bbb;
                margin-bottom: 25px;
            }
            .row {
                font-size: 30px;
                margin: 12px auto;
                width: 900px;
                padding: 14px 20px;
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
                width: 420px;
            }
            .points {
                float: right;
            }
        </style>
    </head>
    <body>
        <div class="title">🔥 6 WEEK CHALLENGE 🔥</div>
        <div class="subtitle">Challenge Score + Lifetime Score</div>
    """

    if not rows:
        html += '<div class="row">NO DATA FOUND</div>'
    else:
        rank = 1
        for row in rows[:10]:
            html += f"""
            <div class="row">
                <span class="rank">#{rank}</span>
                <span class="name">{row['name']}</span>
                <span class="points">C:{int(row['current'])} | L:{int(row['lifetime'])}</span>
            </div>
            """
            rank += 1

    html += """
    </body>
    </html>
    """
    return html


# ============================================================
# CHECK-IN PAGE
# ============================================================

@app.route("/checkin")
def checkin_page():
    dates = challenge_dates()

    html = """
    <html>
    <head>
        <title>TSHRT Attendance</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                margin: 0;
                padding: 20px;
                background: #f8f8f8;
            }
            h2 {
                margin-bottom: 10px;
            }
            .dates {
                margin-bottom: 20px;
            }
            .date {
                display: inline-block;
                padding: 8px 10px;
                margin: 4px;
                border: 1px solid #333;
                border-radius: 6px;
                cursor: pointer;
                background: white;
                font-size: 14px;
            }
            .active {
                background: #222 !important;
                color: white !important;
            }
            .client {
                display: inline-block;
                width: 220px;
                margin: 6px;
                padding: 12px;
                border: 1px solid #333;
                border-radius: 8px;
                cursor: pointer;
                background: #eee;
                font-size: 16px;
            }
            .checked {
                background: #2e7d32 !important;
                color: white !important;
            }
            .count {
                font-size: 22px;
                margin: 12px 0 20px 0;
            }
        </style>
    </head>
    <body>
        <h2>Attendance Board</h2>
        <div class="dates" id="dates">
    """

    for d in dates:
        label = date_label(d)
        html += f'<div class="date" id="d_{d}" onclick="selectDate(\'{d}\')">{label}</div>'

    html += """
        </div>

        <div id="currentDate"></div>
        <div class="count" id="count"></div>
        <div id="clients"></div>

        <script>
            let clients = """ + json.dumps(DATA.get("clients", [])) + """;
            let currentDate = "";

            function selectDate(dateStr) {
                currentDate = dateStr;

                document.querySelectorAll(".date").forEach(el => el.classList.remove("active"));
                let active = document.getElementById("d_" + dateStr);
                if (active) active.classList.add("active");

                document.getElementById("currentDate").innerHTML = "<h3>" + dateStr + "</h3>";

                loadAttendance();
            }

            function loadAttendance() {
                fetch("/api/attendance/" + currentDate)
                    .then(r => r.json())
                    .then(data => {
                        let present = data.attendance || [];
                        let html = "";
                        let count = 0;

                        clients.forEach(c => {
                            let checked = present.includes(c.client_id);
                            if (checked) count++;

                            html += `
                                <div class="client ${checked ? "checked" : ""}" onclick="toggleClient('${c.client_id}')">
                                    ${c.display_name}
                                </div>
                            `;
                        });

                        document.getElementById("clients").innerHTML = html;
                        document.getElementById("count").innerText = "Attendance: " + count + " / " + clients.length;
                    });
            }

            function toggleClient(clientId) {
                fetch("/api/checkin", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        client_id: clientId,
                        date: currentDate
                    })
                }).then(() => loadAttendance());
            }

            let firstDate = document.querySelector(".date");
            if (firstDate) {
                let dateId = firstDate.id.replace("d_", "");
                selectDate(dateId);
            }
        </script>
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
