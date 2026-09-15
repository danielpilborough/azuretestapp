"""
Test app, version 3: same guestbook, but FAST.

The slow version fetched the Key Vault password and opened a brand-new
database connection on EVERY page load. This version does the expensive
setup ONCE and reuses it, which is how a real app (and Django) behaves.

Two changes make the difference:
  1. The Key Vault password is fetched a single time, at startup, and cached.
  2. A single database connection is opened once and reused, reopened only
     if it drops. (Django does this for you via a connection pool; here we
     do it by hand so you can see the idea.)
"""
import os
import threading
import pyodbc
from flask import Flask, request, redirect
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

app = Flask(__name__)

# ---- One-time, cached setup -------------------------------------------------
# These are filled in once, the first time they're needed, then reused.
_password = None          # the Key Vault password, cached after first fetch
_conn = None              # the reused database connection
_lock = threading.Lock()  # stops two requests doing setup at the same time


def get_db_password():
    """Fetch the SQL password from Key Vault ONCE, then return the cached copy."""
    global _password
    if _password is None:
        vault_url = os.environ["KEYVAULT_URL"]
        secret_name = os.environ.get("DB_PASSWORD_SECRET", "sql-password")
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        _password = client.get_secret(secret_name).value  # fetched a single time
    return _password


def _new_connection():
    """Build a fresh database connection (used on first call and after a drop)."""
    server = os.environ["SQL_SERVER"]
    database = os.environ["SQL_DATABASE"]
    username = os.environ["SQL_USER"]
    password = get_db_password()
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def get_cursor():
    """
    Return a cursor on the shared connection, reusing it across requests.
    If the connection has dropped (e.g. the database auto-paused and woke up),
    quietly rebuild it once.
    """
    global _conn
    with _lock:
        if _conn is None:
            _conn = _new_connection()
        try:
            # A cheap no-op to check the connection is still alive.
            _conn.cursor().execute("SELECT 1")
        except pyodbc.Error:
            # Connection went stale - rebuild it.
            _conn = _new_connection()
        return _conn.cursor()


# ---- Ensure the table exists (runs once at startup) -------------------------
def ensure_table():
    cur = get_cursor()
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'guestbook')
        CREATE TABLE guestbook (
            id INT IDENTITY(1,1) PRIMARY KEY,
            message NVARCHAR(400) NOT NULL,
            created_at DATETIME2 DEFAULT SYSDATETIME()
        )
    """)


# Try to prepare the table when the app boots. If the database is asleep this
# may fail; it'll be retried on the first request, so we ignore errors here.
try:
    ensure_table()
except Exception:
    pass


@app.route("/")
def home():
    version = os.environ.get("APP_VERSION", "3")
    error = ""
    rows = []
    try:
        cur = get_cursor()
        cur.execute("SELECT message, created_at FROM guestbook ORDER BY id DESC")
        rows = cur.fetchall()
    except Exception as e:
        error = str(e)

    items = "".join(
        f"<li><span>{r[0]}</span><time>{r[1]:%d %b %H:%M}</time></li>" for r in rows
    ) or "<li class='empty'>No messages yet. Add the first one.</li>"

    error_block = f"<div class='err'><b>Database error:</b><br>{error}</div>" if error else ""

    return f"""
    <!doctype html>
    <html lang="en-GB">
    <head>
      <meta charset="utf-8">
      <title>Compas SQL test</title>
      <style>
        body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
               background:#1B2A5B; color:#fff; margin:0; min-height:100vh;
               display:grid; place-items:center; }}
        .card {{ width:min(560px, 92vw); }}
        .eyebrow {{ font-size:13px; color:#9fb0d9; }}
        .dot {{ width:10px; height:10px; border-radius:50%; background:#C8102E;
               display:inline-block; margin-right:7px; }}
        h1 {{ font-size:34px; margin:6px 0 20px; letter-spacing:-1px; }}
        form {{ display:flex; gap:8px; margin-bottom:22px; }}
        input {{ flex:1; padding:11px 14px; border-radius:8px; border:none; font-size:15px; }}
        button {{ padding:11px 18px; border-radius:8px; border:none; background:#C8102E;
                 color:#fff; font-weight:600; font-size:15px; cursor:pointer; }}
        ul {{ list-style:none; padding:0; margin:0; }}
        li {{ background:rgba(255,255,255,.08); padding:11px 14px; border-radius:8px;
             margin-bottom:7px; display:flex; justify-content:space-between; gap:12px; }}
        li.empty {{ color:#9fb0d9; justify-content:center; }}
        time {{ color:#9fb0d9; font-size:13px; white-space:nowrap; }}
        .err {{ background:#7d1020; padding:14px; border-radius:8px; font-size:13px;
               margin-bottom:20px; line-height:1.5; word-break:break-word; }}
        .v {{ color:#9fb0d9; font-size:12px; margin-top:18px; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="eyebrow"><span class="dot"></span>Compas SQL test</div>
        <h1>Guestbook</h1>
        {error_block}
        <form method="post" action="/add">
          <input name="message" placeholder="Type a message and hit save" maxlength="400" required>
          <button type="submit">Save</button>
        </form>
        <ul>{items}</ul>
        <div class="v">Version {version} - cached secret + reused connection (fast)</div>
      </div>
    </body>
    </html>
    """


@app.route("/add", methods=["POST"])
def add():
    message = (request.form.get("message") or "").strip()
    if message:
        try:
            cur = get_cursor()
            cur.execute("INSERT INTO guestbook (message) VALUES (?)", message)
        except Exception:
            pass
    return redirect("/")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
