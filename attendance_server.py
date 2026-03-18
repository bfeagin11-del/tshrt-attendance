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


# ✅ THIS IS THE MISSING ROUTE
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

    print(f"✅ Roster saved: {len(DATA['clients'])} clients")

    return jsonify({"status": "success", "count": len(DATA["clients"])})


@app.route("/api/checkin", methods=["POST"])
def checkin():
    global DATA

    data = request.get_json()

    client_id = data.get("client_id")
    name = data.get("name")

    today = datetime.now().strftime("%Y-%m-%d")

    if today not in DATA["attendance"]:
        DATA["attendance"][today] = []

    if client_id in DATA["attendance"][today]:
        return jsonify({"status": "duplicate"})

    DATA["attendance"][today].append(client_id)
    DATA["points"][client_id] = DATA["points"].get(client_id, 0) + 1

    save_data(DATA)

    return jsonify({
        "status": "success",
        "points": DATA["points"][client_id]
    })


@app.route("/checkin")
def checkin_page():

    clients = DATA.get("clients", [])

    if not clients:
        return "<h2>No clients loaded. Run sync.</h2>"

    html = """
    <html>
    <head>
        <title>TSHRT Check-In</title>
        <style>
            body { font-family: Arial; text-align: center; }
            .client {
                margin: 10px;
                padding: 15px;
                border: 2px solid #333;
                border-radius: 8px;
                cursor: pointer;
                display: inline-block;
                width: 250px;
                background-color: #f2f2f2;
            }
            .checked { background-color: #4CAF50; color: white; }
            .duplicate { background-color: orange; color: white; }
        </style>
    </head>
    <body>

    <h2>TSHRT Check-In</h2>
    """

    for c in clients:
        cid = c.get("client_id")
        name = c.get("display_name")

        html += f"""
        <div class="client" id="{cid}" onclick="checkin('{cid}','{name}')">
            {name}
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
                el.classList.add("checked");
            }
            else{
                el.classList.add("duplicate");
            }
        });
    }
    </script>

    </body>
    </html>
    """

    return html


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
