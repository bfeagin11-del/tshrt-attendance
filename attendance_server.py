import os
import sqlite3
from datetime import datetime, date, time, timedelta

from flask import Flask, render_template_string, request, redirect, url_for, abort, Response

# ----------------------------
# TSHRT Attendance Cloud Server
# ----------------------------
# This app is designed to run on Render (or locally).
# It maintains its own SQLite database file in the project directory.
#
# Pages:
#   /checkin   - client check-in (time-windowed)
#   /coach     - coach live attendance + approvals
#   /admin     - admin home
#   /admin/roster   - paste/import roster (names + optional group)
#   /admin/challenge - start/view active challenge (phase + dates)
#   /export_attendance - download CSV for local engine import
#
# Security note:
#   Admin pages require ?key=YOUR_KEY where YOUR_KEY is set via environment variable ADMIN_KEY.
#   Set it in Render → Environment → Add Environment Variable.
#
# If you don't set ADMIN_KEY, admin pages are disabled (for safety).

DB_PATH = os.environ.get("TSHRT_ATTENDANCE_DB", "tshrt_attendance.db")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()  # set on Render

CHECKIN_START = time(19, 10)
CHECKIN_END = time(19, 30)

DEFAULT_PHASE = "Hypertrophy"
DEFAULT_CHALLENGE_WEEKS = 6

app = Flask(__name__)


# ----------------------------
# Database helpers
# ----------------------------
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = db_connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                group_name TEXT DEFAULT 'Challenge',
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                phase TEXT NOT NULL,
                status TEXT DEFAULT 'active', -- active/closed
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                session_date TEXT NOT NULL,
                checked_in_at TEXT DEFAULT (datetime('now')),
                approved INTEGER DEFAULT 0,
                approved_at TEXT,
                UNIQUE(client_id, challenge_id, session_date),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
                FOREIGN KEY (challenge_id) REFERENCES challenges(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def ensure_active_challenge():
    """Create a default active challenge if none exists (so check-in works immediately)."""
    conn = db_connect()
    try:
        row = conn.execute("SELECT id FROM challenges WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return int(row["id"])

        start = date.today()
        end = start + timedelta(weeks=DEFAULT_CHALLENGE_WEEKS)
        conn.execute(
            "INSERT INTO challenges (start_date, end_date, phase, status) VALUES (?, ?, ?, 'active')",
            (start.isoformat(), end.isoformat(), DEFAULT_PHASE),
        )
        conn.commit()
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        conn.close()


def get_active_challenge():
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT id, start_date, end_date, phase FROM challenges WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row
    finally:
        conn.close()


def get_clients_grouped():
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT id, full_name, group_name FROM clients WHERE active=1 ORDER BY group_name, full_name"
        ).fetchall()
    finally:
        conn.close()

    groups = {}
    for r in rows:
        g = (r["group_name"] or "Other").strip() or "Other"
        groups.setdefault(g, []).append(r)
    return groups


def record_checkin(client_id: int):
    ch = get_active_challenge()
    if not ch:
        ensure_active_challenge()
        ch = get_active_challenge()
    if not ch:
        return

    conn = db_connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO attendance (client_id, challenge_id, session_date)
            VALUES (?, ?, ?)
            """,
            (int(client_id), int(ch["id"]), date.today().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def approve_checkin(attendance_id: int):
    conn = db_connect()
    try:
        conn.execute(
            """
            UPDATE attendance
            SET approved=1, approved_at=datetime('now')
            WHERE id=?
            """,
            (int(attendance_id),),
        )
        conn.commit()
    finally:
        conn.close()


def unapprove_checkin(attendance_id: int):
    conn = db_connect()
    try:
        conn.execute(
            """
            UPDATE attendance
            SET approved=0, approved_at=NULL
            WHERE id=?
            """,
            (int(attendance_id),),
        )
        conn.commit()
    finally:
        conn.close()


def delete_checkin(attendance_id: int):
    conn = db_connect()
    try:
        conn.execute("DELETE FROM attendance WHERE id=?", (int(attendance_id),))
        conn.commit()
    finally:
        conn.close()


def require_admin():
    if not ADMIN_KEY:
        abort(403)
    key = (request.args.get("key") or "").strip()
    if key != ADMIN_KEY:
        abort(403)


# Initialize DB on import
init_db()
ensure_active_challenge()


# ----------------------------
# Routes: client check-in
# ----------------------------
@app.route("/")
def home():
    return redirect(url_for("checkin"))


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    now = datetime.now().time()

    if not (CHECKIN_START <= now <= CHECKIN_END):
        return "Check-in closed. Window is 19:10–19:30."

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        if client_id.isdigit():
            record_checkin(int(client_id))
        return "✅ Check-in received — awaiting coach approval."

    groups = get_clients_grouped()
    ch = get_active_challenge()

    html = """
    <h1>TSHRT Class Check-In</h1>
    <p><b>Window:</b> 19:10–19:30</p>
    {% if ch %}
      <p><b>Active Challenge:</b> #{{ch['id']}} ({{ch['phase']}}) • {{ch['start_date']}} → {{ch['end_date']}}</p>
    {% endif %}

    {% if not groups %}
      <p><b>No roster loaded yet.</b> Coach: open <code>/admin/roster</code> to paste your roster.</p>
    {% endif %}

    <form method="post">
      {% for group, clients in groups.items() %}
        <h3>{{group}}</h3>
        {% for c in clients %}
          <button style="font-size:18px; padding:10px 14px; margin:6px 0;"
                  name="client_id" value="{{c['id']}}">
            {{c['full_name']}}
          </button><br>
        {% endfor %}
      {% endfor %}
    </form>
    """

    return render_template_string(html, groups=groups, ch=ch)


# ----------------------------
# Routes: coach dashboard + approvals
# ----------------------------
@app.route("/coach", methods=["GET", "POST"])
def coach():
    ch = get_active_challenge()
    if not ch:
        ensure_active_challenge()
        ch = get_active_challenge()

    if request.method == "POST":
        action = request.form.get("action", "")
        att_id = request.form.get("attendance_id", "")
        if action == "approve" and att_id.isdigit():
            approve_checkin(int(att_id))
        elif action == "unapprove" and att_id.isdigit():
            unapprove_checkin(int(att_id))
        elif action == "delete" and att_id.isdigit():
            delete_checkin(int(att_id))
        elif action == "approve_all":
            # approve all for today
            conn = db_connect()
            try:
                conn.execute(
                    """
                    UPDATE attendance
                    SET approved=1, approved_at=datetime('now')
                    WHERE session_date=? AND challenge_id=? AND approved=0
                    """,
                    (date.today().isoformat(), int(ch["id"])),
                )
                conn.commit()
            finally:
                conn.close()

        return redirect(url_for("coach"))

    conn = db_connect()
    try:
        pending = conn.execute(
            """
            SELECT a.id as attendance_id, c.full_name, a.checked_in_at
            FROM attendance a
            JOIN clients c ON c.id = a.client_id
            WHERE a.challenge_id=? AND a.session_date=? AND a.approved=0
            ORDER BY a.checked_in_at ASC
            """,
            (int(ch["id"]), date.today().isoformat()),
        ).fetchall()

        approved = conn.execute(
            """
            SELECT a.id as attendance_id, c.full_name, a.checked_in_at
            FROM attendance a
            JOIN clients c ON c.id = a.client_id
            WHERE a.challenge_id=? AND a.session_date=? AND a.approved=1
            ORDER BY c.full_name ASC
            """,
            (int(ch["id"]), date.today().isoformat()),
        ).fetchall()

        total_active = conn.execute("SELECT COUNT(*) FROM clients WHERE active=1").fetchone()[0]
    finally:
        conn.close()

    html = """
    <h1>TSHRT Coach Dashboard</h1>
    {% if ch %}
      <p><b>Active Challenge:</b> #{{ch['id']}} ({{ch['phase']}}) • {{ch['start_date']}} → {{ch['end_date']}}</p>
    {% endif %}

    <h2>Attendance Today</h2>
    <p><b>{{approved|length}}</b> approved / <b>{{total_active}}</b> on roster</p>

    <form method="post">
      <button name="action" value="approve_all" style="font-size:18px; padding:10px 14px; margin:8px 0;">
        Approve All Pending
      </button>
    </form>

    <h3>Pending Check-ins</h3>
    {% if pending %}
      {% for r in pending %}
        <form method="post" style="margin:6px 0;">
          <input type="hidden" name="attendance_id" value="{{r['attendance_id']}}">
          <span style="font-size:18px;">⏳ {{r['full_name']}}</span>
          <button name="action" value="approve" style="margin-left:10px;">Approve</button>
          <button name="action" value="delete" style="margin-left:6px;">Remove</button>
        </form>
      {% endfor %}
    {% else %}
      <p>No pending check-ins.</p>
    {% endif %}

    <h3>Approved</h3>
    {% if approved %}
      {% for r in approved %}
        <form method="post" style="margin:6px 0;">
          <input type="hidden" name="attendance_id" value="{{r['attendance_id']}}">
          <span style="font-size:18px;">✅ {{r['full_name']}}</span>
          <button name="action" value="unapprove" style="margin-left:10px;">Undo</button>
        </form>
      {% endfor %}
    {% else %}
      <p>No one approved yet.</p>
    {% endif %}
    """
    return render_template_string(html, ch=ch, pending=pending, approved=approved, total_active=total_active)


# ----------------------------
# Admin: roster + challenge
# ----------------------------
@app.route("/admin")
def admin_home():
    require_admin()
    html = """
    <h1>TSHRT Admin</h1>
    <ul>
      <li><a href="/admin/roster?key={{key}}">Roster import</a></li>
      <li><a href="/admin/challenge?key={{key}}">Challenge control</a></li>
      <li><a href="/export_attendance?key={{key}}">Export attendance CSV</a></li>
    </ul>
    """
    return render_template_string(html, key=request.args.get("key", ""))


@app.route("/admin/roster", methods=["GET", "POST"])
def admin_roster():
    require_admin()

    msg = ""
    if request.method == "POST":
        raw = request.form.get("roster", "")
        default_group = (request.form.get("default_group") or "Challenge").strip() or "Challenge"

        # Expected formats per line:
        #   Full Name
        #   Full Name, Group Name
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        conn = db_connect()
        try:
            added = 0
            for ln in lines:
                if "," in ln:
                    name, grp = [x.strip() for x in ln.split(",", 1)]
                    grp = grp or default_group
                else:
                    name, grp = ln, default_group
                if not name:
                    continue
                conn.execute(
                    "INSERT INTO clients (full_name, group_name, active) VALUES (?, ?, 1)",
                    (name, grp),
                )
                added += 1
            conn.commit()
            msg = f"✅ Added {added} clients."
        finally:
            conn.close()

    html = """
    <h1>Roster Import</h1>
    <p>Paste one client per line.</p>
    <p>Optional: add a comma and group name.</p>
    <pre>
Bennie Feagin, Challenge
Luis Ibarra, Open Gym
    </pre>

    {% if msg %}<p><b>{{msg}}</b></p>{% endif %}

    <form method="post">
      <label>Default group:</label>
      <input name="default_group" value="Challenge"><br><br>
      <textarea name="roster" rows="16" cols="50" placeholder="One name per line..."></textarea><br><br>
      <button style="font-size:18px; padding:10px 14px;">Import Roster</button>
    </form>

    <p><a href="/admin?key={{key}}">Back</a></p>
    """
    return render_template_string(html, msg=msg, key=request.args.get("key", ""))


@app.route("/admin/challenge", methods=["GET", "POST"])
def admin_challenge():
    require_admin()
    msg = ""
    if request.method == "POST":
        phase = (request.form.get("phase") or DEFAULT_PHASE).strip() or DEFAULT_PHASE
        start = request.form.get("start_date") or date.today().isoformat()
        weeks = int(request.form.get("weeks") or DEFAULT_CHALLENGE_WEEKS)

        # Close any existing active challenge
        conn = db_connect()
        try:
            conn.execute("UPDATE challenges SET status='closed' WHERE status='active'")
            end = (datetime.fromisoformat(start).date() + timedelta(weeks=weeks)).isoformat()
            conn.execute(
                "INSERT INTO challenges (start_date, end_date, phase, status) VALUES (?, ?, ?, 'active')",
                (start, end, phase),
            )
            conn.commit()
            msg = f"✅ New active challenge started: {phase} ({start} → {end})"
        finally:
            conn.close()

    ch = get_active_challenge()
    html = """
    <h1>Challenge Control</h1>
    {% if msg %}<p><b>{{msg}}</b></p>{% endif %}

    {% if ch %}
      <p><b>Active:</b> #{{ch['id']}} • {{ch['phase']}} • {{ch['start_date']}} → {{ch['end_date']}}</p>
    {% else %}
      <p><b>No active challenge.</b></p>
    {% endif %}

    <h2>Start New Challenge</h2>
    <form method="post">
      <label>Phase:</label>
      <select name="phase">
        <option>Foundation</option>
        <option selected>Hypertrophy</option>
        <option>Strength</option>
        <option>Conditioning</option>
      </select><br><br>

      <label>Start date (YYYY-MM-DD):</label>
      <input name="start_date" value="{{today}}"><br><br>

      <label>Weeks:</label>
      <input name="weeks" value="{{weeks}}"><br><br>

      <button style="font-size:18px; padding:10px 14px;">Start Challenge</button>
    </form>

    <p><a href="/admin?key={{key}}">Back</a></p>
    """
    return render_template_string(
        html,
        msg=msg,
        ch=ch,
        today=date.today().isoformat(),
        weeks=DEFAULT_CHALLENGE_WEEKS,
        key=request.args.get("key", ""),
    )


# ----------------------------
# Export: CSV for local engine import
# ----------------------------
@app.route("/export_attendance")
def export_attendance():
    require_admin()
    ch = get_active_challenge()
    if not ch:
        ensure_active_challenge()
        ch = get_active_challenge()

    conn = db_connect()
    try:
        rows = conn.execute(
            """
            SELECT
              c.full_name as name,
              c.group_name as group_name,
              a.session_date as session_date,
              a.approved as approved
            FROM attendance a
            JOIN clients c ON c.id = a.client_id
            WHERE a.challenge_id=?
            ORDER BY a.session_date ASC, c.full_name ASC
            """,
            (int(ch["id"]),),
        ).fetchall()
    finally:
        conn.close()

    # CSV
    out = ["name,group,session_date,approved"]
    for r in rows:
        out.append(f"{r['name']},{r['group_name']},{r['session_date']},{r['approved']}")
    csv_data = "\n".join(out) + "\n"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=tshrt_attendance_export.csv"},
    )


if __name__ == "__main__":
    # Local run only. On Render, the Start Command runs this file, so this is fine.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
