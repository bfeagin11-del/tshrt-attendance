@app.get("/attendance", response_class=HTMLResponse)
def attendance_page():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>TSHRT Attendance Board</title>
<style>
    :root {{
        --bg: #0f172a;
        --panel: #111827;
        --panel-2: #1f2937;
        --line: #334155;
        --text: #e5e7eb;
        --muted: #94a3b8;
        --accent: #22c55e;
        --accent-2: #16a34a;
        --warning: #f59e0b;
        --button: #2563eb;
        --button-hover: #1d4ed8;
        --chip: #0b1220;
        --shadow: 0 8px 24px rgba(0,0,0,.28);
    }}

    * {{ box-sizing: border-box; }}

    body {{
        margin: 0;
        font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
        background: linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
        color: var(--text);
    }}

    .wrap {{
        max-width: 1600px;
        margin: 0 auto;
        padding: 20px;
    }}

    .topbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        margin-bottom: 18px;
        flex-wrap: wrap;
    }}

    .title-wrap h1 {{
        margin: 0;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: .2px;
    }}

    .title-wrap p {{
        margin: 6px 0 0 0;
        color: var(--muted);
        font-size: 14px;
    }}

    .status-row {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
    }}

    .pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: rgba(255,255,255,.04);
        border: 1px solid var(--line);
        padding: 10px 14px;
        border-radius: 999px;
        font-size: 13px;
        color: var(--text);
    }}

    .dot {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: var(--warning);
        box-shadow: 0 0 0 3px rgba(245,158,11,.15);
    }}

    .dot.ready {{
        background: var(--accent);
        box-shadow: 0 0 0 3px rgba(34,197,94,.15);
    }}

    .controls {{
        display: grid;
        grid-template-columns: repeat(6, minmax(140px, 1fr));
        gap: 12px;
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 16px;
        box-shadow: var(--shadow);
        margin-bottom: 18px;
    }}

    .field {{
        display: flex;
        flex-direction: column;
        gap: 8px;
    }}

    .field label {{
        font-size: 12px;
        color: var(--muted);
        font-weight: 700;
        letter-spacing: .4px;
        text-transform: uppercase;
    }}

    select, input[type="date"] {{
        width: 100%;
        border: 1px solid var(--line);
        background: var(--chip);
        color: var(--text);
        border-radius: 12px;
        padding: 12px;
        font-size: 14px;
        outline: none;
    }}

    .days {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
    }}

    .day-btn {{
        border: 1px solid var(--line);
        background: var(--chip);
        color: var(--text);
        border-radius: 999px;
        padding: 10px 14px;
        cursor: pointer;
        font-weight: 600;
    }}

    .day-btn.active {{
        background: rgba(37,99,235,.16);
        border-color: #3b82f6;
    }}

    .actions {{
        display: flex;
        gap: 10px;
        align-items: end;
        flex-wrap: wrap;
    }}

    button {{
        border: 0;
        border-radius: 14px;
        padding: 12px 16px;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
        transition: transform .05s ease, opacity .2s ease, background .2s ease;
    }}

    button:hover {{ opacity: .96; }}
    button:active {{ transform: translateY(1px); }}

    .btn-primary {{
        background: var(--button);
        color: white;
    }}

    .btn-primary:hover {{
        background: var(--button-hover);
    }}

    .btn-green {{
        background: var(--accent-2);
        color: white;
    }}

    .btn-dark {{
        background: #374151;
        color: white;
    }}

    .btn-outline {{
        background: transparent;
        color: var(--text);
        border: 1px solid var(--line);
    }}

    .summary {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 14px;
    }}

    .card {{
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 14px 16px;
        min-width: 180px;
        box-shadow: var(--shadow);
    }}

    .card .label {{
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .4px;
        margin-bottom: 6px;
        font-weight: 700;
    }}

    .card .value {{
        font-size: 26px;
        font-weight: 800;
    }}

    .table-shell {{
        background: rgba(17,24,39,.95);
        border: 1px solid var(--line);
        border-radius: 20px;
        overflow: hidden;
        box-shadow: var(--shadow);
    }}

    .table-wrap {{
        overflow: auto;
        max-height: 72vh;
    }}

    table {{
        width: max-content;
        min-width: 100%;
        border-collapse: separate;
        border-spacing: 0;
    }}

    thead th {{
        position: sticky;
        top: 0;
        z-index: 3;
        background: #0f172a;
        color: var(--text);
        border-bottom: 1px solid var(--line);
        padding: 12px 10px;
        text-align: center;
        font-size: 12px;
        white-space: nowrap;
    }}

    thead th.sticky-left {{
        left: 0;
        z-index: 4;
        text-align: left;
        min-width: 220px;
    }}

    tbody td, tbody th {{
        border-bottom: 1px solid rgba(148,163,184,.12);
        padding: 10px;
    }}

    tbody th {{
        position: sticky;
        left: 0;
        z-index: 2;
        background: #111827;
        min-width: 220px;
        text-align: left;
        font-size: 14px;
        font-weight: 700;
        cursor: pointer;
    }}

    .sub {{
        display: block;
        color: var(--muted);
        font-weight: 500;
        font-size: 12px;
        margin-top: 3px;
    }}

    .cell {{
        width: 42px;
        min-width: 42px;
        height: 42px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #0b1220;
        cursor: pointer;
        transition: background .15s ease, border-color .15s ease, transform .04s ease;
    }}

    .cell:hover {{
        border-color: #64748b;
    }}

    .cell:active {{
        transform: translateY(1px);
    }}

    .cell.on {{
        background: rgba(34,197,94,.25);
        border-color: var(--accent);
        box-shadow: inset 0 0 0 1px rgba(34,197,94,.3);
    }}

    .legend {{
        display: flex;
        gap: 16px;
        align-items: center;
        color: var(--muted);
        font-size: 13px;
        margin-top: 12px;
        padding: 0 4px 6px;
    }}

    .legend-box {{
        width: 18px;
        height: 18px;
        border-radius: 6px;
        border: 1px solid var(--line);
        background: #0b1220;
        display: inline-block;
        vertical-align: middle;
        margin-right: 6px;
    }}

    .legend-box.on {{
        background: rgba(34,197,94,.25);
        border-color: var(--accent);
    }}

    .toast {{
        position: fixed;
        right: 20px;
        bottom: 20px;
        background: rgba(17,24,39,.98);
        border: 1px solid var(--line);
        color: var(--text);
        border-radius: 14px;
        padding: 14px 16px;
        min-width: 260px;
        box-shadow: var(--shadow);
        display: none;
        z-index: 999;
    }}

    .toast.show {{
        display: block;
    }}

    @media print {{
        .topbar, .controls, .legend, .toast {{
            display: none !important;
        }}
        body {{
            background: white !important;
            color: black !important;
        }}
        .table-shell, .card {{
            box-shadow: none !important;
            border: 1px solid #ccc !important;
            background: white !important;
        }}
        thead th, tbody th {{
            background: white !important;
            color: black !important;
        }}
        .cell {{
            border: 1px solid #999 !important;
            background: white !important;
        }}
        .cell.on {{
            background: #b7f7c3 !important;
            border: 1px solid #4caf50 !important;
        }}
    }}
</style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <div class="title-wrap">
            <h1>TSHRT Attendance Board</h1>
            <p>Cloud-based challenge attendance and group control.</p>
        </div>

        <div class="status-row">
            <div class="pill">
                <span id="serverDot" class="dot"></span>
                <span id="serverStatus">Checking server...</span>
            </div>
            <button class="btn-outline" id="wakeBtn">Wake Server</button>
        </div>
    </div>

    <div class="controls">
        <div class="field">
            <label for="groupSelect">Group</label>
            <select id="groupSelect">
                <option>ABC Class</option>
                <option selected>Gym</option>
                <option>Personal</option>
            </select>
        </div>

        <div class="field">
            <label for="startDate">Challenge Start</label>
            <input id="startDate" type="date" value="{DEFAULT_CHALLENGE_START}" />
        </div>

        <div class="field">
            <label for="endDate">Challenge End</label>
            <input id="endDate" type="date" value="{DEFAULT_CHALLENGE_END}" />
        </div>

        <div class="field">
            <label>Class Days</label>
            <div class="days" id="daysWrap">
                <button class="day-btn active" data-day="0" type="button">Mon</button>
                <button class="day-btn" data-day="1" type="button">Tue</button>
                <button class="day-btn active" data-day="2" type="button">Wed</button>
                <button class="day-btn" data-day="3" type="button">Thu</button>
                <button class="day-btn" data-day="4" type="button">Fri</button>
                <button class="day-btn" data-day="5" type="button">Sat</button>
                <button class="day-btn" data-day="6" type="button">Sun</button>
            </div>
        </div>

        <div class="field actions">
            <button class="btn-primary" id="loadBtn" type="button">Load Board</button>
            <button class="btn-green" id="saveBtn" type="button">Save Attendance</button>
            <button class="btn-dark" id="finalizeBtn" type="button">Finalize Scores</button>
            <button class="btn-outline" onclick="window.print()">Print</button>
        </div>
    </div>

    <div class="summary">
        <div class="card">
            <div class="label">Group</div>
            <div class="value" id="summaryGroup">Gym</div>
        </div>
        <div class="card">
            <div class="label">Clients</div>
            <div class="value" id="summaryClients">0</div>
        </div>
        <div class="card">
            <div class="label">Dates</div>
            <div class="value" id="summaryDates">0</div>
        </div>
        <div class="card">
            <div class="label">Selected Check-ins</div>
            <div class="value" id="summarySelected">0</div>
        </div>
    </div>

    <div class="table-shell">
        <div class="table-wrap" id="boardWrap">
            <table id="boardTable">
                <thead></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>

    <div class="legend">
        <span><span class="legend-box"></span> Not checked in</span>
        <span><span class="legend-box on"></span> Checked in</span>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
    const state = {{
        group: "Gym",
        start: "{DEFAULT_CHALLENGE_START}",
        end: "{DEFAULT_CHALLENGE_END}",
        days: [0, 2],
        dates: [],
        clients: [],
        attendance: {{}}
    }};

    function showToast(message) {{
        const toast = document.getElementById("toast");
        toast.textContent = message;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2600);
    }}

    async function wakeServer() {{
        const dot = document.getElementById("serverDot");
        const status = document.getElementById("serverStatus");
        status.textContent = "Waking server...";
        dot.classList.remove("ready");

        try {{
            const res = await fetch("/debug", {{ cache: "no-store" }});
            if (!res.ok) throw new Error("wake failed");
            status.textContent = "Server ready";
            dot.classList.add("ready");
            return true;
        }} catch (e) {{
            status.textContent = "Server unavailable";
            dot.classList.remove("ready");
            return false;
        }}
    }}

    function getSelectedDays() {{
        return [...document.querySelectorAll(".day-btn.active")].map(btn => Number(btn.dataset.day));
    }}

    function updateSummary() {{
        document.getElementById("summaryGroup").textContent = state.group;
        document.getElementById("summaryClients").textContent = String(state.clients.length);
        document.getElementById("summaryDates").textContent = String(state.dates.length);

        let total = 0;
        for (const clientId of Object.keys(state.attendance)) {{
            total += state.attendance[clientId].length;
        }}
        document.getElementById("summarySelected").textContent = String(total);
    }}

    function shortDate(isoDate) {{
        const d = new Date(isoDate + "T00:00:00");
        return d.toLocaleDateString(undefined, {{ month: "short", day: "numeric" }});
    }}

    function weekdayShort(isoDate) {{
        const d = new Date(isoDate + "T00:00:00");
        return d.toLocaleDateString(undefined, {{ weekday: "short" }});
    }}

    function markWholeDate(date) {{
        for (const client of state.clients) {{
            if (!state.attendance[client.client_id]) {{
                state.attendance[client.client_id] = [];
            }}
            if (!state.attendance[client.client_id].includes(date)) {{
                state.attendance[client.client_id].push(date);
            }}
        }}
        renderBoard();
    }}

    function markWholeClient(clientId) {{
        if (!state.attendance[clientId]) {{
            state.attendance[clientId] = [];
        }}
        for (const date of state.dates) {{
            if (!state.attendance[clientId].includes(date)) {{
                state.attendance[clientId].push(date);
            }}
        }}
        renderBoard();
    }}

    function renderBoard() {{
        const thead = document.querySelector("#boardTable thead");
        const tbody = document.querySelector("#boardTable tbody");

        thead.innerHTML = "";
        tbody.innerHTML = "";

        const trHead = document.createElement("tr");

        const leftHead = document.createElement("th");
        leftHead.className = "sticky-left";
        leftHead.textContent = "Client";
        trHead.appendChild(leftHead);

        for (const date of state.dates) {{
            const th = document.createElement("th");
            th.style.cursor = "pointer";
            th.addEventListener("click", () => markWholeDate(date));
            th.innerHTML = `<div>${weekdayShort(date)}</div><div style="color:var(--muted);margin-top:4px;">${shortDate(date)}</div>`;
            trHead.appendChild(th);
        }}

        thead.appendChild(trHead);

        for (const client of state.clients) {{
            const tr = document.createElement("tr");

            const th = document.createElement("th");
            th.addEventListener("click", () => markWholeClient(client.client_id));
            th.innerHTML = `${{client.display_name || client.client_id}}<span class="sub">${{client.group_name || state.group}}</span>`;
            tr.appendChild(th);

            for (const date of state.dates) {{
                const td = document.createElement("td");
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "cell";

                const selectedDates = state.attendance[client.client_id] || [];
                if (selectedDates.includes(date)) {{
                    btn.classList.add("on");
                }}

                btn.addEventListener("click", () => {{
                    toggleCell(client.client_id, date, btn);
                }});

                td.appendChild(btn);
                tr.appendChild(td);
            }}

            tbody.appendChild(tr);
        }}

        updateSummary();
    }}

    function toggleCell(clientId, date, button) {{
        if (!state.attendance[clientId]) {{
            state.attendance[clientId] = [];
        }}

        const idx = state.attendance[clientId].indexOf(date);

        if (idx >= 0) {{
            state.attendance[clientId].splice(idx, 1);
            button.classList.remove("on");
        }} else {{
            state.attendance[clientId].push(date);
            button.classList.add("on");
        }}

        updateSummary();
    }}

    async function loadBoard() {{
        state.group = document.getElementById("groupSelect").value;
        state.start = document.getElementById("startDate").value;
        state.end = document.getElementById("endDate").value;
        state.days = getSelectedDays();

        if (!state.start || !state.end) {{
            showToast("Please set challenge start and end dates.");
            return;
        }}

        if (state.days.length === 0) {{
            showToast("Select at least one class day.");
            return;
        }}

        const ready = await wakeServer();
        if (!ready) {{
            showToast("Server is not ready yet.");
            return;
        }}

        const params = new URLSearchParams();
        params.set("group", state.group);
        params.set("start", state.start);
        params.set("end", state.end);
        params.set("days", state.days.join(","));

        try {{
            const res = await fetch("/attendance/data?" + params.toString(), {{ cache: "no-store" }});
            if (!res.ok) throw new Error("load failed");

            const data = await res.json();
            state.dates = data.dates || [];
            state.clients = data.clients || [];
            state.attendance = data.attendance || {{}};

            renderBoard();
            showToast("Board loaded.");
        }} catch (e) {{
            showToast("Failed to load attendance board.");
        }}
    }}

    async function saveBoard() {{
        const ready = await wakeServer();
        if (!ready) {{
            showToast("Server is not ready yet.");
            return;
        }}

        try {{
            const res = await fetch("/attendance/save", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{
                    group: state.group,
                    dates: state.dates,
                    selected: state.attendance
                }})
            }});

            if (!res.ok) throw new Error("save failed");

            const data = await res.json();
            showToast("Saved. " + (data.saved || 0) + " check-ins updated.");
        }} catch (e) {{
            showToast("Failed to save attendance.");
        }}
    }}

    document.getElementById("wakeBtn").addEventListener("click", wakeServer);
    document.getElementById("loadBtn").addEventListener("click", loadBoard);
    document.getElementById("saveBtn").addEventListener("click", saveBoard);

    document.getElementById("finalizeBtn").addEventListener("click", () => {{
        showToast("Finalize comes next with leaderboard scoring.");
    }});

    document.querySelectorAll(".day-btn").forEach(btn => {{
        btn.addEventListener("click", () => {{
            btn.classList.toggle("active");
        }});
    }});

    window.addEventListener("load", async () => {{
        await wakeServer();
        await loadBoard();
    }});
</script>
</body>
</html>
    """
