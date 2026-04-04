from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from datetime import date
import sqlite3

app = FastAPI()
DB_PATH = "cloud.db"

# ----------------------
# DATABASE SETUP
# ----------------------

def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        display_name TEXT,
        first_name TEXT,
        last_name TEXT,
        group_name TEXT,
        snapshot_score INTEGER DEFAULT 0,
        baseline_score INTEGER DEFAULT 0,
        in_challenge INTEGER DEFAULT 1
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
    first_name: str
    last_name: str
    group_name: str
    snapshot_score: int = 0
    baseline_score: int = 0
    in_challenge: int = 1


class CheckIn(BaseModel):
    client_id: str
    attended_date: str


# ----------------------
# CORE ROUTES
# ----------------------

@app.get("/debug")
def debug():
    return {"status": "server running"}


@app.post("/sync")
def sync_clients(clients: List[Client]):
    conn = get_conn()
    cur = conn.cursor()

    for c in clients:
        cur.execute("""
        INSERT INTO clients (client_id, display_name, first_name, last_name, group_name, snapshot_score, baseline_score, in_challenge)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            display_name=excluded.display_name,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            group_name=excluded.group_name,
            snapshot_score=excluded.snapshot_score,
            baseline_score=excluded.baseline_score,
            in_challenge=excluded.in_challenge
        """, (
            c.client_id,
            c.display_name,
            c.first_name,
            c.last_name,
            c.group_name,
            c.snapshot_score,
            c.baseline_score,
            c.in_challenge
        ))

    conn.commit()
    conn.close()

    return {"status": "clients synced", "count": len(clients)}


@app.post("/checkin")
def checkin(data: CheckIn):
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("""
        INSERT INTO attendance (client_id, attended_date)
        VALUES (?, ?)
        """, (data.client_id, data.attended_date))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Already checked in")

    conn.close()
    return {"status": "checked in"}


@app.get("/board")
def board():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT client_id, display_name, snapshot_score, baseline_score FROM clients WHERE in_challenge=1")
    clients = cur.fetchall()

    result = []

    for c in clients:
        client_id, name, snapshot, baseline = c

        cur.execute("SELECT COUNT(*) FROM attendance WHERE client_id=?", (client_id,))
        attendance_count = cur.fetchone()[0]

        current_score = snapshot + attendance_count
        lifetime_score = baseline + current_score

        result.append({
            "client_id": client_id,
            "name": name,
            "attendance": attendance_count,
            "current_score": current_score,
            "lifetime_score": lifetime_score
        })

    conn.close()

    return sorted(result, key=lambda x: x["current_score"], reverse=True)


@app.get("/display")
def display():
    data = board()

    return [
        {
            "name": x["name"],
            "score": x["current_score"]
        }
        for x in data
    ]
