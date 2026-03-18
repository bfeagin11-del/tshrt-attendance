from flask import Flask, request, jsonify
from datetime import datetime
import os
import json

app = Flask(__name__)

DATA_FILE = "roster_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "clients": [],
        "attendance": {},
        "points": {}
    }

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

DATA = load_data()


@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


# =========================
# ROSTER SYNC
# =========================
@app.route("/api/roster/sync", methods=["POST"])
def roster_sync():
    global DATA

    incoming = request.get_json()

    if not incoming or "clients" not in incoming:
        return jsonify({"status": "error"}), 400

    DATA["clients"] = incoming["clients"]

    for c in DATA["clients"]:
        cid = c.get("client_id")
        if cid not in DATA["points"]:
            DATA["points"][cid] = 0

    save_data(DATA)

    return jsonify({"status": "success", "count": len(DATA["clients"])})


# =========================
# TOGGLE CHECK-IN (FULL CONTROL)
# =========================
@app.route("/api/checkin", methods=["POST"])
def checkin():
    global DATA

    data = request.get_json()

    client_id = data.get("client_id")
    date = data.get("date")

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    if date not in DATA["attendance"]:
        DATA["attendance"][date] = []

    # TOGGLE
    if client_id in DATA["attendance"][date]:
        DATA["attendance"][date].remove(client_id)
        DATA["points"][client_id] = max(0, DATA["points"].get(client_id, 0) - 1)
        save_data(DATA)
        return jsonify({"status": "removed"})
    else:
        DATA["attendance"][date].append(client_id)
        DATA["points"][client_id] = DATA["points"].get(client_id, 0) + 1
        save_data(DATA)
        return jsonify({"status": "added"})


# =========================
# GET ATTENDANCE BY DATE
# =========================
@app.route("/api/attendance/<date>", methods=["GET"])
def get_attendance(date):
    return jsonify({
        "attendance": DATA["attendance"].get(date, []),
        "total": len(DATA["attendance"].get(date, []))
    })


# =========================
# CHECK-IN PAGE (FULL UI)
# =========================
@app.route("/checkin")
def checkin_page():

    html = """
    <html>
    <head>
        <title>TSHRT Attendance</title>
        <style>
            body { font-family: Arial; text-align: center; }
            .client {
                margin: 8px;
                padding: 12px;
                border: 2px solid #333;
                border-radius: 8px;
                cursor: pointer;
                display: inline-block;
                width: 220px;
                background-color: #eee;
            }
            .checked { background-color: #4CAF50; color: white; }
            .header { margin-bottom: 20px; }
        </style>
    </head>
    <body>

    <h2>TSHRT Attendance</h2>

    <div class="header">
        <input type="date" id="datePicker">
        <h3 id="count"></h3>
    </div>

    <div id="clients"></div>

    <script>
    let clients = """ + json.dumps(DATA["clients"]) + """;

    function loadAttendance(){
        let date = document.getElementById("datePicker").value;

        fetch("/api/attendance/" + date)
        .then(r=>r.json())
        .then(data=>{
            let present = data.attendance;

            document.getElementById("count").innerHTML =
                "Attendance: " + data.total + " / " + clients.length;

            let html = "";

            clients.forEach(c=>{
                let checked = present.includes(c.client_id);

                html += `
                <div class="client ${checked ? 'checked' : ''}"
                    onclick="toggle('${c.client_id}')"
                    id="${c.client_id}">
                    ${c.display_name}
                </div>`;
            });

            document.getElementById("clients").innerHTML = html;
        });
    }

    function toggle(id){
        let date = document.getElementById("datePicker").value;

        fetch('/api/checkin', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({
                client_id:id,
                date:date
            })
        })
        .then(()=>loadAttendance());
    }

    // DEFAULT TODAY
    let today = new Date().toISOString().split('T')[0];
    document.getElementById("datePicker").value = today;

    loadAttendance();
    </script>

    </body>
    </html>
    """

    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
