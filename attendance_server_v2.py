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
        present INTEGER DEFAULT 1,
        finalized INTEGER DEFAULT 0,
        UNIQUE(client_id, attended_date)
    )
    """)

    conn.commit()
    conn.close()

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

init_db()
upgrade_db()

# =========================================================
# WAKE
# =========================================================

@app.get("/wake")
def wake():
    return {"status": "awake"}

# =========================================================
# SYNC
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
    return {"status": "synced"}

# =========================================================
# LOAD CLIENTS
# =========================================================

@app.get("/attendance/data")
def attendance_data(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT *
        FROM clients
        WHERE LOWER(TRIM(COALESCE(group_name,''))) = LOWER(TRIM(?))
        ORDER BY last_name, first_name
    """, (group,)).fetchall()

    conn.close()

    clients = []
    for r in rows:
        first = r["first_name"] or ""
        last = r["last_name"] or ""

        if (not first or not last) and r["display_name"]:
            if "," in r["display_name"]:
                parts = [p.strip() for p in r["display_name"].split(",", 1)]
                last = last or parts[0]
                first = first or (parts[1] if len(parts) > 1 else "")

        clients.append({
            "client_id": r["client_id"],
            "first_name": first,
            "last_name": last
        })

    return {"clients": clients}

# =========================================================
# LOAD ATTENDANCE
# =========================================================

@app.get("/attendance/load")
def load_attendance(group: str):
    conn = get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT a.client_id, a.attended_date
        FROM attendance a
        JOIN clients c ON a.client_id = c.client_id
        WHERE LOWER(TRIM(COALESCE(c.group_name,''))) = LOWER(TRIM(?))
    """, (group,)).fetchall()

    conn.close()

    selected = {}
    for r in rows:
        selected[f"{r['client_id']}_{r['attended_date']}"] = True

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

    for client_id, dates in payload.selected.items():
        for d in dates:
            cur.execute("""
            INSERT INTO attendance (client_id, attended_date, present)
            VALUES (?, ?, 1)
            ON CONFLICT(client_id, attended_date) DO UPDATE SET present=1
            """, (client_id, d))

    if payload.finalize_date:
        cur.execute("""
        UPDATE attendance SET finalized=1 WHERE attended_date=?
        """, (payload.finalize_date,))

    conn.commit()
    conn.close()

    return {"status": "saved"}

# =========================================================
# UI
# =========================================================

@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return """
<html>
<head>
<style>
body { background:#0f172a; color:white; font-family:sans-serif; }
table { border-collapse:collapse; }
td, th { border:1px solid #334155; padding:8px; text-align:center; }
.name { text-align:left; background:#1f2937; min-width:180px; }
.cell { width:40px; height:40px; cursor:pointer; }
.active { background:#22c55e; }
th { background:#1e293b; font-size:12px; }
</style>
</head>
<body>

<h2>TSHRT Attendance Board</h2>

Group:
<select id="group">
<option>ABC Class</option>
<option>Gym</option>
<option>Personal</option>
</select>

Start: <input type="date" id="start" value="2026-03-09">
End: <input type="date" id="end" value="2026-04-20">

<label><input type="checkbox" value="1" checked>Mon</label>
<label><input type="checkbox" value="3" checked>Wed</label>

<button onclick="loadBoard()">Load</button>
<button onclick="saveBoard()">Save</button>
<button onclick="finalize()">Finalize</button>
<button onclick="wake()">Wake</button>

<table id="grid"></table>

<script>
let state={clients:[],dates:[],selected:{}};

function buildDates(){
    let s=new Date(start.value+"T12:00:00");
    let e=new Date(end.value+"T12:00:00");
    let arr=[];
    let days=[1,3];

    while(s<=e){
        if(days.includes(s.getDay())){
            let y=s.getFullYear();
            let m=String(s.getMonth()+1).padStart(2,"0");
            let d=String(s.getDate()).padStart(2,"0");
            arr.push(`${y}-${m}-${d}`);
        }
        s.setDate(s.getDate()+1);
    }
    return arr;
}

function formatDate(d){
    let dt=new Date(d+"T12:00:00");
    return dt.toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric"});
}

async function loadBoard(){
    try {
        let g = group.value;

        let c = await fetch("/attendance/data?group=" + encodeURIComponent(g));
        let clients = await c.json();

        let a = await fetch("/attendance/load?group=" + encodeURIComponent(g));
        let att = await a.json();

        console.log("CLIENTS:", clients);
        console.log("ATTENDANCE:", att);

        state.clients = clients.clients || [];
        state.selected = att.selected || {};
        state.dates = buildDates();

        render();

    } catch (err) {
        console.error("LOAD ERROR:", err);
        alert("Load failed — check console (F12)");
    }
}

function render(){
    let html="<tr><th>Name</th>";
    state.dates.forEach(d=>html+="<th>"+formatDate(d)+"</th>");
    html+="</tr>";

    state.clients.forEach(c=>{
        html+="<tr><td class='name'>"+c.last_name+", "+c.first_name+"</td>";
        state.dates.forEach(d=>{
            let k=c.client_id+"_"+d;
            let cls=state.selected[k]?"cell active":"cell";
            html+="<td class='"+cls+"' onclick=\"toggle('"+c.client_id+"','"+d+"')\"></td>";
        });
        html+="</tr>";
    });

    grid.innerHTML=html;
}

function toggle(id,d){
    let k=id+"_"+d;
    state.selected[k]?delete state.selected[k]:state.selected[k]=true;
    render();
}

async function saveBoard(){
    let payload={};
    for(let k in state.selected){
        let [id,...d]=k.split("_");
        d=d.join("_");
        if(!payload[id])payload[id]=[];
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
    let d = prompt("Enter date to finalize (YYYY-MM-DD)");
    if (!d) return;

    await fetch("/attendance/save", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            selected: {},
            finalize_date: d
        })
    });

    alert("Finalized " + d);
}
async function wake(){
    await fetch("/wake");
    alert("Awake");
}
</script>

</body>
</html>
"""
