# attendance_server.py

from flask import Flask, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

# ============================================================
# STORAGE
# ============================================================

CLIENT_ROSTER = []
ATTENDANCE = {}
POINTS = {}

# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


# ============================================================
# ROSTER SYNC
# ============================================================

@app.route("/api/roster/sync", methods=["POST"])
def roster_sync():
    global CLIENT_ROSTER, POINTS

    data = request.get_json()

    if not data or "clients" not in data:
        return jsonify({"status": "error"}), 400

    CLIENT_ROSTER = data["clients"]

    # initialize points
    for c in CLIENT_ROSTER:
        cid = c.get("client_id")
        if cid not in POINTS:
            POINTS[cid] = 0

    print(f"\n✅ Roster synced: {len(CLIENT_ROSTER)} clients\n")

    return jsonify({"status": "success", "count": len(CLIENT_ROSTER)})


# ============================================================
# CHECK-IN ENDPOINT
# ============================================================

@app.route("/api/checkin", methods=["POST"])
def checkin():
    data = request.get_json()

    client_id = data.get("client_id")
    name = data.get("name")

    if not client_id:
        return jsonify({"status": "error", "message": "missing id"}), 400

    today = datetime.now().strftime("%Y-%m-%d")

    # attendance tracking
    if today not in ATTENDANCE:
        ATTENDANCE[today] = set()

    if client_id in ATTENDANCE[today]:
        return jsonify({
            "status": "duplicate",
            "message": f"{name} already checked in"
        })

    ATTENDANCE[today].add(client_id)

    # update points
    POINTS[client_id] = POINTS.get(client_id, 0) + 1

    print(f"✅ CHECK-IN: {name} | Points: {POINTS[client_id]}")

    return jsonify({
        "status": "success",
        "client_id": client_id,
        "name": name,
        "points": POINTS[client_id],
        "date": today
    })


# ============================================================
# GET ATTENDANCE (FOR REPORTING)
# ============================================================

@app.route("/api/attendance", methods=["GET"])
def get_attendance():
    return jsonify({
        "attendance": {k: list(v) for k, v in ATTENDANCE.items()},
        "points": POINTS
    })


# ============================================================
# CHECK-IN PAGE (INTERACTIVE)
# ============================================================

@app.route("/checkin")
def checkin_page():

    html = "<h2>TSHRT Check-In</h2>"

    for c in CLIENT_ROSTER:
        cid = c.get("client_id")
        name = c.get("display_name")

        html += f"""
        <div style="margin:10px;">
            <button onclick="checkin('{cid}', '{name}')">{name}</button>
            <span id="{cid}"></span>
        </div>
        """

    html += """
    <script>
    function checkin(id, name){
        fetch('/api/checkin', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({client_id:id, name:name})
        })
        .then(r=>r.json())
        .then(data=>{
            let el = document.getElementById(id);

            if(data.status === 'success'){
                el.innerHTML = " ✅ Checked In (" + data.points + " pts)";
            }
            else if(data.status === 'duplicate'){
                el.innerHTML = " ⚠ Already Checked In";
            }
        });
    }
    </script>
    """

    return html


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
