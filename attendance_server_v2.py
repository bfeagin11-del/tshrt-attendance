from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List
import sqlite3

app = FastAPI()
DB_PATH = "cloud.db"

# ----------------------
# DB CONNECTION
# ----------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------
# INIT DB
# ----------------------

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        first_name TEXT,
        last_name TEXT,
        group_name TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        attended_date TEXT,
        UNIQUE(client_id, attended_date)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ----------------------
# MODELS
# ----------------------

class Client(BaseModel):
    client_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    group_name: str = ""

# ----------------------
# SYNC (OPTION 17)
# ----------------------

@app.post("/sync")
def sync_clients(clients: List[Client]):
    conn = get_conn()
    cur = conn.cursor()

    for c in clients:
        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name=excluded.display_name,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            group_name=excluded.group_name
        """, (
            c.client_id,
            c.display_name,
            c.first_name,
            c.last_name,
            c.group_name
        ))

    conn.commit()
    conn.close()

    return {"status": "clients synced", "count": len(clients)}

# ----------------------
# LOAD DATA
# ----------------------

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients WHERE group_name=?", (group,))
    rows = cur.fetchall()

    clients = []
    for r in rows:
        clients.append({
            "client_id": r["client_id"],
            "display_name": r["display_name"],
            "first_name": r["first_name"],
            "last_name": r["last_name"]
        })

    conn.close()

    return {"clients": clients}

# ----------------------
# SAVE
# ----------------------

@app.post("/attendance/save")
def save_attendance(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    for client_id, dates in data.get("selected", {}).items():
        for d in dates:
            try:
                cur.execute("""
                INSERT INTO attendance (client_id, attended_date)
                VALUES (?, ?)
                """, (client_id, d))
                saved += 1
            except:
                pass

    conn.commit()
    conn.close()

    return {"saved": saved}

# ----------------------
# UI (YOUR BOARD)
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<head>
<style>
<style>
body {
    background:#0f172a;
    color:white;
    font-family:sans-serif;
}

.controls {
    margin-bottom:20px;
}

table {
    border-collapse: collapse;
    margin-top:10px;
}

td, th {
    border:1px solid #334155;
    padding:10px;
    text-align:center;
    font-size:16px;
}

.name {
    text-align:left;
    background:#1f2937;
    padding-left:12px;
    min-width:180px;
    font-weight:500;
}

.cell {
    width:40px;
    height:40px;
    cursor:pointer;
}

.active {
    background:#22c55e;
}

th {
    background:#1e293b;
}
</style>
</head>

<body>

<h2>TSHRT Attendance</h2>

<div class="controls">

Group:
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

Start:
<input type="date" id="start" value="2026-03-09">

End:
<input type="date" id="end" value="2026-04-20">

Days:
<label><input type="checkbox" value="1" checked>Mon</label>
<label><input type="checkbox" value="3" checked>Wed</label>

<button onclick="load()">Load</button>
<button onclick="save()">Save</button>

</div>

<table id="grid"></table>

<script>

let state = {
    clients: [],
    dates: [],
    selected: {}
};

function getSelectedDays() {
    let checks = document.querySelectorAll("input[type=checkbox]:checked");
    return Array.from(checks).map(c => parseInt(c.value));
}

function buildDates() {
    let start = new Date(document.getElementById("start").value);
    let end = new Date(document.getElementById("end").value);
    let days = getSelectedDays();

    let dates = [];

    while (start <= end) {
        if (days.includes(start.getDay())) {
            from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List
import sqlite3

app = FastAPI()
DB_PATH = "cloud.db"

# ----------------------
# DB CONNECTION
# ----------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------
# INIT DB
# ----------------------

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        first_name TEXT,
        last_name TEXT,
        group_name TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        attended_date TEXT,
        UNIQUE(client_id, attended_date)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ----------------------
# MODELS
# ----------------------

class Client(BaseModel):
    client_id: str
    display_name: str
    first_name: str = ""
    last_name: str = ""
    group_name: str = ""

# ----------------------
# SYNC (OPTION 17)
# ----------------------

@app.post("/sync")
def sync_clients(clients: List[Client]):
    conn = get_conn()
    cur = conn.cursor()

    for c in clients:
        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name=excluded.display_name,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            group_name=excluded.group_name
        """, (
            c.client_id,
            c.display_name,
            c.first_name,
            c.last_name,
            c.group_name
        ))

    conn.commit()
    conn.close()

    return {"status": "clients synced", "count": len(clients)}

# ----------------------
# LOAD DATA
# ----------------------

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM clients WHERE group_name=?", (group,))
    rows = cur.fetchall()

    clients = []
    for r in rows:
        clients.append({
            "client_id": r["client_id"],
            "display_name": r["display_name"],
            "first_name": r["first_name"],
            "last_name": r["last_name"]
        })

    conn.close()

    return {"clients": clients}

# ----------------------
# SAVE
# ----------------------

@app.post("/attendance/save")
def save_attendance(data: dict):
    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    for client_id, dates in data.get("selected", {}).items():
        for d in dates:
            try:
                cur.execute("""
                INSERT INTO attendance (client_id, attended_date)
                VALUES (?, ?)
                """, (client_id, d))
                saved += 1
            except:
                pass

    conn.commit()
    conn.close()

    return {"saved": saved}

# ----------------------
# UI (YOUR BOARD)
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<head>
<style>
body {
    background:#0f172a;
    color:white;
    font-family:sans-serif;
}

.controls {
    margin-bottom:15px;
}

table {
    border-collapse: collapse;
}

td, th {
    border:1px solid #334155;
    padding:6px;
    text-align:center;
}

.name {
    text-align:left;
    background:#1f2937;
    padding-left:10px;
}

.cell {
    width:28px;
    height:28px;
    cursor:pointer;
}

.active {
    background:#22c55e;
}
</style>
</head>

<body>

<h2>TSHRT Attendance</h2>

<div class="controls">

Group:
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

Start:
<input type="date" id="start" value="2026-03-09">

End:
<input type="date" id="end" value="2026-04-20">

Days:
<label><input type="checkbox" value="1" checked>Mon</label>
<label><input type="checkbox" value="3" checked>Wed</label>

<button onclick="load()">Load</button>
<button onclick="save()">Save</button>

</div>

<table id="grid"></table>

<script>

let state = {
    clients: [],
    dates: [],
    selected: {}
};

function getSelectedDays() {
    let checks = document.querySelectorAll("input[type=checkbox]:checked");
    return Array.from(checks).map(c => parseInt(c.value));
}

function buildDates() {
    let start = new Date(document.getElementById("start").value);
    let end = new Date(document.getElementById("end").value);
    let days = getSelectedDays();

    let dates = [];

    while (start <= end) {
        if (days.includes(start.getDay())) {
            dates.push(start.toISOString().slice(0,10));
        }
        start.setDate(start.getDate() + 1);
    }

    return dates;
}

async function load() {
    let group = document.getElementById("group").value;

    let res = await fetch("/attendance/data?group=" + encodeURIComponent(group));
    let data = await res.json();

    state.clients = data.clients;
    state.dates = buildDates();

    render();
}

function render() {
    let html = "<tr><th class='name'>Name</th>";

    for (let d of state.dates) {
        html += "<th>" + d.slice(5) + "</th>";
    }

    html += "</tr>";

    state.clients.sort((a,b)=>{
        if (a.last_name === b.last_name) {
            return a.first_name.localeCompare(b.first_name);
        }
        return a.last_name.localeCompare(b.last_name);
    });

    for (let c of state.clients) {
        html += "<tr>";
        html += "<td class='name'>" + c.last_name + ", " + c.first_name + "</td>";

        for (let d of state.dates) {
            let key = c.client_id + "_" + d;
            let cls = state.selected[key] ? "cell active" : "cell";

            html += "<td class='" + cls + "' onclick=\\"toggle('" + c.client_id + "','" + d + "')\\"></td>";
        }

        html += "</tr>";
    }

    document.getElementById("grid").innerHTML = html;
}

function toggle(id, date) {
    let key = id + "_" + date;

    if (state.selected[key]) {
        delete state.selected[key];
    } else {
        state.selected[key] = true;
    }

    render();
}

async function save() {
    let payload = {};

    for (let key in state.selected) {
        let parts = key.split("_");
        let id = parts[0];
        let date = parts.slice(1).join("_");

        if (!payload[id]) payload[id] = [];
        payload[id].push(date);
    }

    let res = await fetch("/attendance/save", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({selected: payload})
    });

    let data = await res.json();
    alert("Saved " + data.saved);
}

</script>

</body>
</html>
"""
        }
        start.setDate(start.getDate() + 1);
    }

    return dates;
}

async function load() {
    let group = document.getElementById("group").value;

    let res = await fetch("/attendance/data?group=" + encodeURIComponent(group));
    let data = await res.json();

    state.clients = data.clients;
    state.dates = buildDates();

    render();
}

function render() {
    let html = "<tr><th class='name'>Name</th>";

    for (let d of state.dates) {
        html += "<th>" + d.slice(5) + "</th>";
    }

    html += "</tr>";

    state.clients.sort((a,b)=>{
        if (a.last_name === b.last_name) {
            return a.first_name.localeCompare(b.first_name);
        }
        return a.last_name.localeCompare(b.last_name);
    });

    for (let c of state.clients) {
        html += "<tr>";
        html += "<td class='name'>" + c.last_name + ", " + c.first_name + "</td>";

        for (let d of state.dates) {
            let key = c.client_id + "_" + d;
            let cls = state.selected[key] ? "cell active" : "cell";

            html += "<td class='" + cls + "' onclick=\\"toggle('" + c.client_id + "','" + d + "')\\"></td>";
        }

        html += "</tr>";
    }

    document.getElementById("grid").innerHTML = html;
}

function toggle(id, date) {
    let key = id + "_" + date;

    if (state.selected[key]) {
        delete state.selected[key];
    } else {
        state.selected[key] = true;
    }

    render();
}

async function save() {
    let payload = {};

    for (let key in state.selected) {
        let parts = key.split("_");
        let id = parts[0];
        let date = parts.slice(1).join("_");

        if (!payload[id]) payload[id] = [];
        payload[id].push(date);
    }

    let res = await fetch("/attendance/save", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({selected: payload})
    });

    let data = await res.json();
    alert("Saved " + data.saved);
}

</script>

</body>
</html>
"""
