"""
Test app, version 2: now talks to Azure SQL.

It's a tiny "guestbook": type a message, it writes it to the database,
and the page lists every message stored. That proves three things at once:
  - the app can REACH the database (firewall + connection details)
  - the app can WRITE to it (INSERT)
  - the app can READ from it (SELECT)

The database PASSWORD is never written in this file. It's pulled at
startup from Azure Key Vault, using the app's own identity. That's the
part worth understanding: the code holds no secret, just the NAME of the
secret to go and fetch.
"""
import os
import pyodbc
from flask import Flask, request, redirect
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

app = Flask(__name__)


def get_db_password():
    """
    Fetch the SQL password from Key Vault.

    DefaultAzureCredential is the clever bit: when running in Azure, it
    automatically uses the app's managed identity (no login, no secret in
    code). The app just says "I am who Azure says I am", and Key Vault
    checks whether that identity is allowed to read the secret.
    """
    vault_url = os.environ["KEYVAULT_URL"]          # e.g. https://compas-test-kv.vault.azure.net/
    secret_name = os.environ.get("DB_PASSWORD_SECRET", "sql-password")
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)
    return client.get_secret(secret_name).value


def get_connection():
    """Open a connection to Azure SQL using details from settings + the Key Vault password."""
    server = os.environ["SQL_SERVER"]        # e.g. compas-test-sql.database.windows.net
    database = os.environ["SQL_DATABASE"]    # e.g. compasdb
    username = os.environ["SQL_USER"]        # the admin login you set when creating the DB
    password = get_db_password()             # <-- from Key Vault, not from here

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server};DATABASE={database};"
        f"UID={username};PWD={password};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"
    )
    return pyodbc.connect(conn_str)


def ensure_table():
    """Create the guestbook table the first time, if it isn't there yet."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'guestbook')
            CREATE TABLE guestbook (
                id INT IDENTITY(1,1) PRIMARY KEY,
                message NVARCHAR(400) NOT NULL,
                created_at DATETIME2 DEFAULT SYSDATETIME()
            )
        """)
        conn.commit()


@app.route("/")
def home():
    version = os.environ.get("APP_VERSION", "2")
    error = ""
    rows = []
    try:
        ensure_table()
        with get_connection() as conn:
            cur = conn.cursor()
            # READ: newest first
            cur.execute("SELECT message, created_at FROM guestbook ORDER BY id DESC")
            rows = cur.fetchall()
    except Exception as e:
        # If anything's wrong (firewall, Key Vault permission, wrong setting),
        # show it on the page so you can see WHAT failed rather than a blank error.
        error = str(e)

    # Build the list of messages as simple HTML
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
        <div class="v">Version {version} - reading and writing to Azure SQL - password from Key Vault</div>
      </div>
    </body>
    </html>
    """


@app.route("/add", methods=["POST"])
def add():
    """WRITE: store a new message, then go back to the list."""
    message = (request.form.get("message") or "").strip()
    if message:
        try:
            ensure_table()
            with get_connection() as conn:
                cur = conn.cursor()
                # Parameterised (?) - never glue user text straight into SQL.
                cur.execute("INSERT INTO guestbook (message) VALUES (?)", message)
                conn.commit()
        except Exception:
            pass  # the home page will show the error on next load
    return redirect("/")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

