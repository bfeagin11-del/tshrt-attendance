# attendance_server.py

from flask import Flask, request, jsonify, render_template
import json
import os

app = Flask(__name__)

# ============================================================
# GLOBAL STORAGE (simple + fast for now)
# ============================================================

CLIENT_ROSTER = []

# ============================================================
# EXISTING ROUTES (KEEP YOUR CURRENT ONES IF YOU HAVE CUSTOM)
# ============================================================

@app.route("/")
def home():
    return "TSHRT Attendance Server Running"


@app.route("/challenge_board")
def challenge_board():
    return "Challenge Board Active"


# ============================================================
# 🔥 NEW: ROSTER SYNC ENDPOINT
# ============================================================

@app.route("/api/roster/sync", methods=["POST"])
def roster_sync():
    global CLIENT_ROSTER

    data = request.get_json()

    if not data or "clients" not in data:
        return jsonify({
            "status": "error",
            "message": "No clients provided"
        }), 400

    CLIENT_ROSTER = data["clients"]

    print(f"\n✅ Roster synced: {len(CLIENT_ROSTER)} clients\n")

    return jsonify({
        "status": "success",
        "count": len(CLIENT_ROSTER)
    })


# ============================================================
# 🔥 NEW: GET ROSTER (FOR QR PAGE)
# ============================================================

@app.route("/api/roster", methods=["GET"])
def get_roster():
    return jsonify({
        "clients": CLIENT_ROSTER
    })


# ============================================================
# 🔥 EXAMPLE QR CHECK-IN PAGE SUPPORT
# ============================================================

@app.route("/checkin")
def checkin_page():
    names = [c.get("display_name", "Unknown") for c in CLIENT_ROSTER]
    return "<br>".join(names)


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
