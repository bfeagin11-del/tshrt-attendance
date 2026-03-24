import os
import json
import urllib.request

DATA_DIR = r"C:\TSHRT\Data"
RENDER_URL = "https://tshrt-attendance.onrender.com/api/roster/sync"


# ==============================
# LOAD CLIENT FILES
# ==============================

def load_clients():
    clients = []

    for file in os.listdir(DATA_DIR):
        if not file.endswith(".json"):
            continue

        path = os.path.join(DATA_DIR, file)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            continue

        first = data.get("first_name", "")
        last = data.get("last_name", "")
        name = f"{first} {last}".strip()

        client_id = file.replace(".json", "").lower()

        tests = data.get("tests", [])
        if not tests:
            continue

        # ==============================
        # CURRENT SCORE (latest test)
        # ==============================
        latest = tests[-1]
        current_score = int(latest.get("snapshot_score", latest.get("score", 0)))

        # ==============================
        # BASELINE SCORE (before challenge)
        # ==============================
        baseline_score = 0

        for t in tests:
            date = t.get("date", "")
            if date and date < "2026-03-09":
                baseline_score = int(t.get("score", 0))

        clients.append({
            "client_id": client_id,
            "display_name": name,
            "snapshot_score": current_score,
            "baseline_score": baseline_score
        })

    return clients


# ==============================
# SYNC TO RENDER
# ==============================

def sync_to_cloud():
    clients = load_clients()

    payload = json.dumps({
        "clients": clients
    }).encode("utf-8")

    req = urllib.request.Request(
        RENDER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as res:
            print("\n=== SYNC SUCCESS ===")
            print(res.read().decode())
    except Exception as e:
        print("\n=== SYNC FAILED ===")
        print(str(e))


# ==============================
# OPTION 17 ENTRY POINT
# ==============================

def option_17_sync():
    print("\nSYNCING CLIENT DATA + SCORES...")
    sync_to_cloud()


# ==============================
# PRINT SUMMARY (optional)
# ==============================

def print_sync_summary(result=None):
    print("\nSYNC COMPLETE")
