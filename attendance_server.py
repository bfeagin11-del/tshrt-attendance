from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import os, json

app = Flask(__name__)

DATA_FILE = "roster_data.json"
CHALLENGE_START = "2026-03-10"


# =========================
# LOAD / SAVE
# =========================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)

    return {
        "clients": [],
        "attendance": {},
        "challenges": {
            "current": {},
            "history": {}
        }
    }


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(DATA, f)


DATA = load_data()


# =========================
# SYNC CLIENTS
# =========================
@app.route("/api/roster/sync", methods=["POST"])
def sync():
    incoming = request.get_json()
    DATA["clients"] = incoming.get("clients", [])

    for c in DATA["clients"]:
        cid = c["client_id"]

        DATA["challenges"]["current"].setdefault(cid, 0)
        DATA["challenges"]["history"].setdefault(cid, [])

    save_data()
    return jsonify({"status": "ok"})


# =========================
# CHECK-IN
# =========================
@app.route("/api/checkin", methods=["POST"])
def checkin():
    data = request.get_json()
    cid = data["client_id"]
    date = data["date"]

    if date not in DATA["attendance"]:
        DATA["attendance"][date] = []

    if cid in DATA["attendance"][date]:
        DATA["attendance"][date].remove(cid)
        DATA["challenges"]["current"][cid] -= 1
    else:
        DATA["attendance"][date].append(cid)
        DATA["challenges"]["current"][cid] += 1

    save_data()
    return jsonify({"status": "ok"})


# =========================
# LOCK CHALLENGE
# =========================
@app.route("/lock_challenge")
def lock_challenge():

    for cid, score in DATA["challenges"]["current"].items():
        if score > 0:
            DATA["challenges"]["history"][cid].append(score)
            DATA["challenges"]["current"][cid] = 0

    save_data()
    return "Challenge locked!"


# =========================
# LEADERBOARD
# =========================
@app.route("/board")
def board():

    rows = []

    for c in DATA["clients"]:
        cid = c["client_id"]
        name = c["display_name"]

        current = DATA["challenges"]["current"].get(cid, 0)
        history = DATA["challenges"]["history"].get(cid, [])

        lifetime = sum(history) + current

        rows.append({
            "name": name,
            "current": current,
            "lifetime": lifetime
        })

    rows.sort(key=lambda x: x["current"], reverse=True)

    html = """
    <html>
    <head>
    <style>
    body { background:black; color:white; font-family:Arial; text-align:center; }

    .title { font-size:48px; margin:20px; }

    .row {
        font-size:28px;
        margin:10px auto;
        width:600px;
        padding:10px;
        border-bottom:1px solid #444;
    }
    </style>
    </head>
    <body>

    <div class="title">🔥 CHALLENGE BOARD 🔥</div>
    """

    rank = 1
    for r in rows[:10]:
        html += f"""
        <div class="row">
            #{rank} {r['name']} — C:{r['current']} | L:{r['lifetime']}
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

    html = f"<h2>Attendance</h2>"

    html += "<div>"
    for d in dates:
        html += f"<a href='/day/{d}'>{d}</a> | "
    html += "</div>"

    return html


@app.route("/day/<date>")
def day(date):

    present = DATA["attendance"].get(date, [])

    html = f"<h3>{date}</h3>"

    for c in DATA["clients"]:
        cid = c["client_id"]
        name = c["display_name"]

        checked = "✔" if cid in present else "❌"

        html += f"""
        <div>
            {name} {checked}
            <a href="/toggle/{cid}/{date}">[toggle]</a>
        </div>
        """

    return html


@app.route("/toggle/<cid>/<date>")
def toggle(cid, date):

    if date not in DATA["attendance"]:
        DATA["attendance"][date] = []

    if cid in DATA["attendance"][date]:
        DATA["attendance"][date].remove(cid)
        DATA["challenges"]["current"][cid] -= 1
    else:
        DATA["attendance"][date].append(cid)
        DATA["challenges"]["current"][cid] += 1

    save_data()
    return "OK"


# =========================
# RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
