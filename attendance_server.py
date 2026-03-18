# attendance_server.py

from flask import Flask, request, jsonify
from datetime import datetime
import os
import json

app = Flask(__name__)

# ============================================================
# FILE STORAGE
# ============================================================

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

# ============================================================
# HOME
# ============================================================

@app.route("/checkin")
def checkin_page():

    html = """
    <html>
    <head>
        <title>TSHRT Check-In</title>
        <style>
            body {
                font-family: Arial;
                text-align: center;
            }
            .client {
                margin: 10px;
                padding: 15px;
                border: 2px solid #333;
                border-radius: 8px;
                cursor: pointer;
                display: inline-block;
                width: 250px;
                background-color: #f2f2f2;
                transition: 0.2s;
            }
            .client:hover {
                background-color: #ddd;
            }
            .checked {
                background-color: #4CAF50 !important;
                color: white;
            }
            .duplicate {
                background-color: #f39c12 !important;
                color: white;
            }
        </style>
    </head>
    <body>

    <h2>TSHRT Check-In</h2>
    """

    for c in CLIENT_ROSTER:
        cid = c.get("client_id")
        name = c.get("display_name")

        html += f"""
        <div class="client" id="{cid}" onclick="checkin('{cid}', '{name}')">
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
                el.innerHTML = name + " ✔";
            }
            else if(data.status === 'duplicate'){
                el.classList.add("duplicate");
                el.innerHTML = name + " (Already)";
            }
        });
    }
    </script>

    </body>
    </html>
    """

    return html

    for c in CLIENT_ROSTER:
        cid = c.get("client_id")
        name = c.get("display_name")

        html += f"""
        <div class="client" id="{cid}" onclick="checkin('{cid}', '{name}')">
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
                el.innerHTML = name + " ✔";
            }
            else if(data.status === 'duplicate'){
                el.classList.add("duplicate");
                el.innerHTML = name + " (Already)";
            }
        });
    }
    </script>

    </body>
    </html>
    """

    return html

# ============================================================
# CHECK-IN PAGE
# ============================================================

@app.route("/checkin")
def checkin_page():

    html = "<h2>TSHRT Check-In</h2>"

    clients = DATA.get("clients", [])

    if not clients:
        return "<h2>No clients loaded. Run sync.</h2>"

    for c in clients:
        cid = c.get("client_id")
        name = c.get("display_name")

        html += f"""
        <div style="margin:10px;">
            <button onclick="checkin('{cid}','{name}')">{name}</button>
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
                el.innerHTML = " ✅ (" + data.points + " pts)";
            }
            else{
                el.innerHTML = " ⚠ Already";
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
