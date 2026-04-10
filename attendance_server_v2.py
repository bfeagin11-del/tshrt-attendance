from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3

app = FastAPI()
DB_PATH = "/data/cloud.db"

# ----------------------
# DB CONNECTION
# ----------------------

import os

def get_conn():
    os.makedirs("/data", exist_ok=True)  # 🔥 ensures folder exists

    conn = sqlite3.connect("/data/cloud.db", check_same_thread=False)
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
# DEBUG
# ----------------------

@app.get("/debug")
def debug():
    return {"status": "server running"}

# ----------------------
# SYNC (YOU ALREADY HAVE THIS WORKING)
# ----------------------

@app.post("/sync")
def sync_clients(clients: list):
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
            c.get("client_id"),
            c.get("display_name"),
            c.get("first_name"),
            c.get("last_name"),
            c.get("group_name")
        ))

    conn.commit()
    conn.close()

    return {"status": "synced", "count": len(clients)}

# ----------------------
# BOARD
# ----------------------

@app.get("/board")
def board():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT client_id, display_name, first_name, last_name, group_name
        FROM clients
        ORDER BY last_name, first_name
    """)
    clients = cur.fetchall()

    result = []

    for c in clients:
        cur.execute("""
            SELECT COUNT(*) as cnt
            FROM attendance
            WHERE client_id=?
        """, (c["client_id"],))
        count = cur.fetchone()["cnt"]

        result.append({
            "client_id": c["client_id"],
            "name": c["display_name"],
            "group": c["group_name"],
            "attendance": count,
            "current_score": count,
            "lifetime_score": count
        })

    conn.close()
    return result

# ----------------------
# LOAD CLIENTS FOR UI
# ----------------------

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM clients
        WHERE group_name = ?
        ORDER BY last_name, first_name
    """, (group,))

    rows = cur.fetchall()

    clients = []
    for r in rows:
        clients.append({
            "client_id": r["client_id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"]
        })

    conn.close()

    return {"clients": clients}

# ----------------------
# SAVE ATTENDANCE (ONLY ONE VERSION)
# ----------------------

@app.post("/attendance/save")
async def save_attendance(request: Request):
    data = await request.json()
    selected = data.get("selected", {})

    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    for client_id, dates in selected.items():
        for d in dates:
            cur.execute("""
                INSERT OR IGNORE INTO attendance (client_id, attended_date)
                VALUES (?, ?)
            """, (client_id, d))
            saved += 1

    conn.commit()
    conn.close()

    return {"saved": saved}

# ----------------------
# UI
# ----------------------

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<head>
<style>
body { background:#0f172a; color:white; font-family:sans-serif; }
.controls { margin-bottom:20px; }
table { border-collapse:collapse; }
td, th { border:1px solid #334155; padding:10px; text-align:center; }
.name { text-align:left; background:#1f2937; padding-left:12px; min-width:180px; }
.cell { width:40px; height:40px; cursor:pointer; }
.active { background:#22c55e; }
th { background:#1e293b; }
</style>
</head>

<body>

<h2>TSHRT Attendance Board</h2>

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

<button onclick="loadBoard()">Load</button>
<button onclick="saveBoard()">Save</button>
</div>

<table id="grid"></table>

<script>
let state = { clients:[], dates:[], selected:{} };

function getDays(){
    return Array.from(document.querySelectorAll("input[type=checkbox]:checked")).map(c=>parseInt(c.value));
}

function buildDates(){
    let s=new Date(start.value), e=new Date(end.value), d=getDays(), arr=[];
    while(s<=e){
        if(d.includes(s.getDay())){
            arr.push(s.toISOString().slice(0,10));
        }
        s.setDate(s.getDate()+1);
    }
    return arr;
}

async function loadBoard(){
    let g=group.value;
    let res=await fetch("/attendance/data?group="+encodeURIComponent(g));
    let data=await res.json();
    state.clients=data.clients;
    state.dates=buildDates();
    render();
}

function render(){
    let html="<tr><th class='name'>Name</th>";
    for(let d of state.dates){ html+="<th>"+d.slice(5)+"</th>"; }
    html+="</tr>";

    for(let c of state.clients){
        html+="<tr><td class='name'>"+c.last_name+", "+c.first_name+"</td>";
        for(let d of state.dates){
            let k=c.client_id+"_"+d;
            let cls=state.selected[k]?"cell active":"cell";
            html+="<td class='"+cls+"' onclick=\"toggle('"+c.client_id+"','"+d+"')\"></td>";
        }
        html+="</tr>";
    }

    grid.innerHTML=html;
}

function toggle(id,date){
    let k=id+"_"+date;
    state.selected[k]?delete state.selected[k]:state.selected[k]=true;
    render();
}

async function saveBoard(){
    let payload={};
    for(let k in state.selected){
        let [id,...d]=k.split("_");
        d=d.join("_");
        if(!payload[id]) payload[id]=[];
        payload[id].push(d);
    }

    let res=await fetch("/attendance/save",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({selected:payload})
    });

    let data=await res.json();
    alert("Saved "+data.saved);
}
</script>

</body>
</html>
"""
