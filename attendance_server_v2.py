from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import os
from typing import List, Dict

app = FastAPI()

# =========================================================
# DB SETUP
# =========================================================

DB_PATH = "/data/cloud.db"

def get_conn():
    os.makedirs("/data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # CLIENTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        first_name TEXT,
        last_name TEXT,
        group_name TEXT
    )
    """)

    # ATTENDANCE (with finalized flag)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        attended_date TEXT,
        present INTEGER DEFAULT 1,
        finalized INTEGER DEFAULT 0,
        UNIQUE(client_id, attended_date)
    )
    """)

    conn.commit()
    conn.close()

init_db()

def upgrade_db():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN present INTEGER DEFAULT 1")
    except:
        pass

    try:
        cur.execute("ALTER TABLE attendance ADD COLUMN finalized INTEGER DEFAULT 0")
    except:
        pass

    conn.commit()
    conn.close()
# =========================================================
# DEBUG / WAKE
# =========================================================

@app.get("/debug")
def debug():
    return {"status": "server running"}

@app.get("/wake")
def wake():
    return {"status": "awake"}

# =========================================================
# SYNC (CLEAN — ONLY ONE VERSION)
# =========================================================

class SyncPayload(BaseModel):
    clients: List[dict]

@app.post("/sync")
def sync_clients(payload: SyncPayload):
    conn = get_conn()
    cur = conn.cursor()

    for c in payload.clients:
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

    return {"status": "synced", "count": len(payload.clients)}

# =========================================================
# LOAD CLIENTS
# =========================================================

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
    conn.close()

    return {
        "clients": [
            {
                "client_id": r["client_id"],
                "first_name": r["first_name"],
                "last_name": r["last_name"]
            } for r in rows
        ]
    }

# =========================================================
# LOAD ATTENDANCE
# =========================================================

@app.get("/attendance/load")
def load_attendance(group: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.client_id, a.attended_date, a.present
        FROM attendance a
        JOIN clients c ON a.client_id = c.client_id
        WHERE c.group_name = ?
    """, (group,))

    rows = cur.fetchall()
    conn.close()

    selected = {}
    for r in rows:
        key = f"{r['client_id']}_{r['attended_date']}"
        selected[key] = True

    return {"selected": selected}

# =========================================================
# SAVE ATTENDANCE
# =========================================================

class SavePayload(BaseModel):
    selected: Dict[str, List[str]]
    finalize_date: str | None = None

@app.post("/attendance/save")
def save_attendance(payload: SavePayload):
    conn = get_conn()
    cur = conn.cursor()

    saved = 0

    # SAVE PRESENT
    for client_id, dates in payload.selected.items():
        for d in dates:
            cur.execute("""
            INSERT INTO attendance (client_id, attended_date, present)
            VALUES (?, ?, 1)
            ON CONFLICT(client_id, attended_date) DO UPDATE SET
                present=1
            """, (client_id, d))
            saved += 1

    # FINALIZE DATE
    if payload.finalize_date:
        cur.execute("""
        UPDATE attendance
        SET finalized = 1
        WHERE attended_date = ?
        """, (payload.finalize_date,))

    conn.commit()
    conn.close()

    return {"saved": saved}

# =========================================================
# UI (YOUR BOARD — ENHANCED)
# =========================================================

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
.locked { background:#475569; }
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
<button onclick="finalize()">Finalize</button>
<button onclick="wakeServer()">Wake Server</button>
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
        if(d.includes(s.getDay())) arr.push(s.toISOString().slice(0,10));
        s.setDate(s.getDate()+1);
    }
    return arr;
}

async function loadBoard(){
    let g=group.value;

    let clientsRes = await fetch("/attendance/data?group="+g);
    let clientsData = await clientsRes.json();

    let attRes = await fetch("/attendance/load?group="+g);
    let attData = await attRes.json();

    state.clients = clientsData.clients;
    state.selected = attData.selected || {};
    state.dates = buildDates();

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
            html+="<td class='"+cls+"' onclick=\\"toggle('"+c.client_id+"','"+d+"')\\"></td>";
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

    await fetch("/attendance/save",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({selected:payload})
    });

    alert("Saved");
}

async function finalize(){
    let d=prompt("Enter date to finalize (YYYY-MM-DD)");
    if(!d) return;

    await fetch("/attendance/save",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({selected:{}, finalize_date:d})
    });

    alert("Finalized "+d);
}

async function wakeServer(){
    await fetch("/wake");
    alert("Server Awake");
}
</script>

</body>
</html>
"""
