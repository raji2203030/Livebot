from flask import Flask, render_template, request, redirect, jsonify
import gspread
from google.oauth2.service_account import Credentials
import os
import time

app = Flask(
    __name__,
    template_folder="templates",
)

# CONFIG
CREDENTIALS_FILE = "credentials.json"
SHEET_ID = os.getenv("SHEET_ID", "1Tbzu3LjBdZxcAneZv1d6wjft6ApM-fbmwvisFjyRTAY")
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# UI visibility controls
SHOW_TABLE = os.getenv("SHOW_TABLE", "false").lower() == "true"
MAX_VISIBLE_ROWS = int(os.getenv("MAX_VISIBLE_ROWS", "0"))  # 0 = no limit
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "25"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "15"))  # cache sheet values for N seconds
SHEET_REAUTH_SECONDS = int(os.getenv("SHEET_REAUTH_SECONDS", "3600"))  # reuse client up to N seconds

# In-memory caches
_sheet_singleton = {"sheet": None, "ts": 0.0}
_cached_data = {"headers": [], "rows": [], "fetched_at": 0.0}

def get_sheet():
    # Reuse the gspread client/sheet for a while to avoid re-auth overhead
    now = time.time()
    if _sheet_singleton["sheet"] is not None and (now - _sheet_singleton["ts"]) < SHEET_REAUTH_SECONDS:
        return _sheet_singleton["sheet"]
    try:
        # Check if we're on Railway (environment variable exists)
        if os.getenv("GOOGLE_CREDENTIALS"):
            import json
            creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        else:
            # Local development - use credentials.json file
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPE)
        
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        _sheet_singleton["sheet"] = sheet
        _sheet_singleton["ts"] = now
        return sheet
    except Exception as exc:
        app.logger.error(f"Failed to initialize Google Sheet client: {exc}")
        return None


def get_sheet_data(force: bool = False):
    now = time.time()
    # Serve from cache if fresh
    if not force and _cached_data["fetched_at"] and (now - _cached_data["fetched_at"]) < CACHE_TTL_SECONDS:
        return _cached_data["headers"], _cached_data["rows"]

    sheet = get_sheet()
    if sheet is None:
        return [], []
    data = sheet.get_all_values()
    headers = data[0] if data else []
    rows = data[1:] if len(data) > 1 else []
    _cached_data.update({
        "headers": headers,
        "rows": rows,
        "fetched_at": now,
    })
    return headers, rows


@app.route("/")
def index():
    headers, rows = get_sheet_data()
    if not headers and not rows:
        return render_template(
            "index.html",
            headers=[],
            rows=[],
            error_message="Google Sheets credentials not found or invalid. Place a valid credentials.json in the project root.",
            show_table=SHOW_TABLE,
        )

    # Apply UI visibility/limits
    if SHOW_TABLE:
        if MAX_VISIBLE_ROWS and len(rows) > MAX_VISIBLE_ROWS:
            rows = rows[-MAX_VISIBLE_ROWS:]
    else:
        headers, rows = [], []

    return render_template("index.html", headers=headers, rows=rows, error_message=None, show_table=SHOW_TABLE)


@app.route("/add", methods=["POST"])
def add_row():
    sheet = get_sheet()
    if sheet is None:
        return redirect("/")
    name = request.form.get("name")
    email = request.form.get("email")
    age = request.form.get("age")
    sheet.append_row([name, email, age])
    return redirect("/")


# ✅ New endpoint: get the latest row only
@app.route("/get_latest")
def get_latest():
    headers, rows = get_sheet_data()
    if not headers and not rows:
        return jsonify({"row": []})
    if not rows:
        return jsonify({"row": []})
    latest_row = rows[-1]
    return jsonify({"row": latest_row})


# ✅ New endpoint: search rows by query term (case-insensitive substring across any column)
@app.route("/search")
def search_rows():
    query = (request.args.get("q") or "").strip().lower()
    if not query:
        return jsonify({"headers": [], "rows": []})

    headers, rows = get_sheet_data()
    if not headers and not rows:
        return jsonify({"headers": [], "rows": []})
    
    filtered = [row for row in rows if any(query in str(cell).lower() for cell in row)]
    
    # Limit results
    if MAX_SEARCH_RESULTS and len(filtered) > MAX_SEARCH_RESULTS:
        filtered = filtered[:MAX_SEARCH_RESULTS]
    
    return jsonify({"headers": headers, "rows": filtered})


# --- Basic small-talk and chat router ---
def _basic_chat_response(query: str) -> str | None:
    q = (query or "").strip().lower()
    if not q:
        return None

    greetings = {"hi", "hello", "hey", "yo", "hola"}
    if any(word in q for word in greetings) or q in greetings:
        return (
            "Hello! I can search your Google Sheet. Ask things like: "
            "'Find rows with john', 'emails with @gmail.com', or 'age 30'."
        )

    if "help" in q or "how" in q and "use" in q:
        return (
            "Try: 'search alice', 'email contains @company.com', or 'age 25'. "
            f"I'll return up to {MAX_SEARCH_RESULTS} results."
        )

    if "who are you" in q or ("what" in q and "you" in q and "do" in q):
        return (
            "I'm your sheet bot. I read your configured Google Sheet and return matching rows."
        )

    if "show table" in q or "display table" in q:
        return (
            "For privacy, the table is hidden by default. Set SHOW_TABLE=true and refresh to enable it."
        )

    if "clear" in q:
        return (
            "I don't store chat history. Refresh the page to clear the conversation view."
        )

    return None


@app.route("/chat")
def chat_router():
    query = request.args.get("q", "")
    basic = _basic_chat_response(query)
    if basic is not None:
        return jsonify({"type": "text", "text": basic})

    # Fallback to search semantics
    sheet = get_sheet()
    if sheet is None:
        return jsonify({"type": "text", "text": "Sheets access is not configured (credentials.json missing or invalid)."})

    data = sheet.get_all_values() or []
    if not data:
        return jsonify({"type": "text", "text": "The sheet appears to be empty."})

    headers = data[0]
    rows = data[1:] if len(data) > 1 else []
    q = (query or "").strip().lower()
    if not q:
        return jsonify({"type": "text", "text": "Please enter something to search."})

    filtered = [row for row in rows if any(q in str(cell).lower() for cell in row)]
    if MAX_SEARCH_RESULTS and len(filtered) > MAX_SEARCH_RESULTS:
        filtered = filtered[:MAX_SEARCH_RESULTS]

    return jsonify({"type": "table", "headers": headers, "rows": filtered})


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
