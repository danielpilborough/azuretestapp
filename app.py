"""
Compas dashboard - visual demo with a few live, editable data points.

This serves the Compas dashboard in the Calex design language. Most of it is
a visual mockup (static sample data), exactly as designed. Two areas are
genuinely live and backed by Azure SQL:

  - Contact queue: real tickets from the database; you can ADD a new one.
  - Contacts:      real people from the database; you can ADD a new one.

A couple of dashboard stats (open ticket count, contact count) are derived
from the live data too, so numbers on the page reflect the database.

Secrets: the SQL password is fetched once from Key Vault at startup and
cached; the DB connection is reused. Same pattern as the fast test app.
"""
import os
import threading
import functools
import pyodbc
from flask import Flask, request, redirect, render_template, session, url_for
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

app = Flask(__name__)
# Session secret. In Azure this comes from an env var; locally a default is fine.
# Sessions are how the mock login "remembers" who is logged in across pages.
app.secret_key = os.environ.get("FLASK_SECRET", "compas-demo-not-secret")

# ---- Mock login: three roles ----
# NOTE: demo gate only - passwords in code, not real security. Real auth
# (Entra ID) comes with the Django build.
#   admin  - sees everything
#   user   - standard staff; sees a restricted subset of data
#   dealer - external; simple "raise a ticket + my queries" view only
DEMO_USERS = {
    "admin":  {"password": "admin",  "name": "Admin",       "role": "admin",  "initials": "AD", "sub": "Full access"},
    "user":   {"password": "user",   "name": "Staff User",  "role": "user",   "initials": "SU", "sub": "Standard access"},
    "dealer": {"password": "dealer", "name": "Dealer",      "role": "dealer", "initials": "DL", "sub": "Dealer portal"},
}

# Which staff member the "user" role is scoped to (their own assigned work).
# In a real app this would be the logged-in person's own identity.
USER_SCOPE_NAME = "Staff User"


def login_required(view):
    """Redirect to the login page if there's no logged-in user in the session."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    """Return the logged-in user's record, or None."""
    uid = session.get("user")
    return DEMO_USERS.get(uid) if uid else None

_password = None
_conn = None
_lock = threading.Lock()


def get_db_password():
    global _password
    if _password is None:
        vault_url = os.environ["KEYVAULT_URL"]
        secret_name = os.environ.get("DB_PASSWORD_SECRET", "sql-password")
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=vault_url, credential=credential)
        _password = client.get_secret(secret_name).value
    return _password


def _new_connection():
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['SQL_SERVER']};DATABASE={os.environ['SQL_DATABASE']};"
        f"UID={os.environ['SQL_USER']};PWD={get_db_password()};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"
    )
    return pyodbc.connect(conn_str, autocommit=True)


def get_cursor():
    global _conn
    with _lock:
        if _conn is None:
            _conn = _new_connection()
        try:
            _conn.cursor().execute("SELECT 1")
        except pyodbc.Error:
            _conn = _new_connection()
        return _conn.cursor()


def ensure_tables():
    """Create the two live tables the first time, and seed a little sample data."""
    cur = get_cursor()
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'tickets')
        CREATE TABLE tickets (
            id INT IDENTITY(1,1) PRIMARY KEY,
            subject NVARCHAR(300) NOT NULL,
            requester NVARCHAR(200) NOT NULL,
            site NVARCHAR(200) NULL,
            channel NVARCHAR(40) NOT NULL DEFAULT 'email',
            priority NVARCHAR(20) NOT NULL DEFAULT 'med',
            status NVARCHAR(20) NOT NULL DEFAULT 'open',
            assigned_to NVARCHAR(200) NULL,
            raised_by NVARCHAR(200) NULL,
            created_at DATETIME2 DEFAULT SYSDATETIME()
        )
    """)
    # Migrate: add the two role columns if an older tickets table already exists.
    cur.execute("""
        IF COL_LENGTH('tickets', 'assigned_to') IS NULL
        ALTER TABLE tickets ADD assigned_to NVARCHAR(200) NULL
    """)
    cur.execute("""
        IF COL_LENGTH('tickets', 'raised_by') IS NULL
        ALTER TABLE tickets ADD raised_by NVARCHAR(200) NULL
    """)
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'contacts')
        CREATE TABLE contacts (
            id INT IDENTITY(1,1) PRIMARY KEY,
            name NVARCHAR(200) NOT NULL,
            dealer NVARCHAR(200) NULL,
            email NVARCHAR(200) NULL,
            created_at DATETIME2 DEFAULT SYSDATETIME()
        )
    """)
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'actions')
        CREATE TABLE actions (
            id INT IDENTITY(1,1) PRIMARY KEY,
            title NVARCHAR(300) NOT NULL,
            due NVARCHAR(40) NULL,
            done BIT NOT NULL DEFAULT 0,
            created_at DATETIME2 DEFAULT SYSDATETIME()
        )
    """)
    # Seed sample rows only if the tables are empty, so the demo looks populated.
    cur.execute("SELECT COUNT(*) FROM tickets")
    if cur.fetchone()[0] == 0:
        # (subject, requester, site, channel, priority, status, assigned_to, raised_by)
        seed = [
            ("Accreditation certificate not showing", "J. Okafor", "Sytner Audi Leeds", "whatsapp", "high", "open", "Staff User", "Dealer"),
            ("Course code AUD-334 booking failed", "Booking desk", "Marshall VW Peterborough", "phone", "high", "open", None, None),
            ("New starter account request (x3)", "L. Freeman", "TPS Birmingham", "email", "med", "pending", "Priya S.", None),
            ("Question about CUPRA training path", "Booking desk", "Swansway CUPRA", "email", "med", "progress", "Staff User", "Dealer"),
            ("Feedback: LEAP module 4 content", "R. Green", "Skoda Derby", "ticket", "med", "open", None, None),
            ("Portal login not working", "Dealer", "Swansway CUPRA", "ticket", "low", "open", "Priya S.", "Dealer"),
        ]
        for row in seed:
            cur.execute(
                "INSERT INTO tickets (subject, requester, site, channel, priority, status, assigned_to, raised_by) VALUES (?,?,?,?,?,?,?,?)",
                *row)
    cur.execute("SELECT COUNT(*) FROM contacts")
    if cur.fetchone()[0] == 0:
        seed = [
            ("J. Okafor", "Sytner Audi Leeds", "j.okafor@sytner.example"),
            ("L. Freeman", "TPS Birmingham", "l.freeman@tps.example"),
            ("R. Green", "Skoda Derby", "r.green@skoda.example"),
        ]
        for row in seed:
            cur.execute("INSERT INTO contacts (name, dealer, email) VALUES (?,?,?)", *row)
    cur.execute("SELECT COUNT(*) FROM actions")
    if cur.fetchone()[0] == 0:
        seed = [
            ("Assign the two unassigned high-priority tickets", "Today", 0),
            ("Approve TPS Birmingham new-starter accounts", "Today", 0),
            ("Review LEAP module 4 feedback with content team", "Tomorrow", 0),
            ("Send March pre-booking targeting to CUPRA sites", "Fri", 1),
        ]
        for row in seed:
            cur.execute("INSERT INTO actions (title, due, done) VALUES (?,?,?)", *row)


def fetch_all(role="admin"):
    """
    Read the live data, filtered by role, and derive stats.
      admin  - every ticket
      user   - only tickets assigned to them, or unassigned (their workload)
      dealer - only tickets they raised
    The filtering is real SQL (a WHERE clause), not a cosmetic hide.
    """
    cur = get_cursor()

    base = """
        SELECT id, subject, requester, site, channel, priority, status, assigned_to, raised_by
        FROM tickets
    """
    order = " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'med' THEN 1 ELSE 2 END, id DESC"

    if role == "dealer":
        cur.execute(base + " WHERE raised_by = ?" + order, "Dealer")
    elif role == "user":
        # Their own assigned work, plus anything unassigned (up for grabs).
        cur.execute(base + " WHERE assigned_to = ? OR assigned_to IS NULL" + order, USER_SCOPE_NAME)
    else:  # admin
        cur.execute(base + order)

    tickets = [dict(id=r[0], subject=r[1], requester=r[2], site=r[3],
                    channel=r[4], priority=r[5], status=r[6],
                    assigned_to=r[7], raised_by=r[8]) for r in cur.fetchall()]

    cur.execute("SELECT id, name, dealer, email FROM contacts ORDER BY id DESC")
    contacts = [dict(id=r[0], name=r[1], dealer=r[2], email=r[3]) for r in cur.fetchall()]

    cur.execute("SELECT id, title, due, done FROM actions ORDER BY done ASC, id DESC")
    action_items = [dict(id=r[0], title=r[1], due=r[2], done=bool(r[3])) for r in cur.fetchall()]

    open_count = sum(1 for t in tickets if t["status"] == "open")
    high_count = sum(1 for t in tickets if t["priority"] == "high")
    open_action_count = sum(1 for a in action_items if not a["done"])
    return dict(tickets=tickets, contacts=contacts, action_items=action_items,
                open_count=open_count, high_count=high_count,
                open_action_count=open_action_count,
                ticket_count=len(tickets), contact_count=len(contacts))


# Small inline SVG icons for the nav, matching the design's line style.
def _svg(*paths):
    body = "".join('<path d="%s"/>' % p for p in paths)
    return ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">%s</svg>' % body)

ICONS = dict(
    ico_home=_svg("M3 10.5 12 3l9 7.5", "M5 9v11h14V9"),
    ico_contact=_svg("M4 5h16v12H8l-4 3z"),
    ico_users=_svg("M8 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2 20c0-3.3 2.7-6 6-6s6 2.7 6 6",
                   "M16 5.2a3.5 3.5 0 0 1 0 6.6", "M17 14.2c2.9.5 5 2.9 5 5.8"),
    ico_reports=_svg("M4 20V10M10 20V4M16 20v-7M22 20H2"),
    ico_forms=_svg("M7 3h10a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M9 8h6M9 12h6M9 16h3"),
    ico_actions=_svg("M9 11l2 2 4-4", "M4 4h16v16H4z"),
    ico_comm=_svg("M3 6h18v11H8l-5 4z", "M7 10h10M7 13h6"),
    ico_know=_svg("M4 5a1 1 0 0 1 1-1h5a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H5a1 1 0 0 1-1-1z",
                  "M20 5a1 1 0 0 0-1-1h-5a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h5a1 1 0 0 0 1-1z"),
    ico_target=_svg("M12 3v4M12 17v4M3 12h4M17 12h4", "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"),
    ico_pbi=_svg("M5 20V12h4v8M11 20V6h4v14M17 20v-5h4v5M2 20h20"),
    ico_reviews=_svg("M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 9.7l5.4-.8z"),
    ico_dealers=_svg("M4 20V9l8-5 8 5v11", "M9 20v-6h6v6"),
    ico_hub=_svg("M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"),
    ico_audit=_svg("M9 4H7a1 1 0 0 0-1 1v15a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1h-2",
                   "M9 3h6v3H9z", "M9 12h6M9 16h4"),
    ico_check=('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" '
               'stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 5 5L20 7"/></svg>'),
)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        uid = (request.form.get("username") or "").strip().lower()
        pw = (request.form.get("password") or "").strip()
        user = DEMO_USERS.get(uid)
        if user and user["password"] == pw:
            session["user"] = uid
            return redirect(url_for("home"))
        error = "Wrong username or password. Try one of the demo users below."
    if "user" in session:
        return redirect(url_for("home"))
    return render_template("login.html", error=error, demo_users=DEMO_USERS, **ICONS)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    user = current_user()
    # Dealers get a simple, separate view - not the internal dashboard.
    if user["role"] == "dealer":
        return redirect(url_for("dealer_home"))
    error = ""
    data = dict(tickets=[], contacts=[], action_items=[], open_count=0, high_count=0,
                open_action_count=0, ticket_count=0, contact_count=0)
    try:
        ensure_tables()
        data = fetch_all(role=user["role"])
    except Exception as e:
        error = str(e)
    return render_template("dashboard.html", error=error, user=user, **data, **ICONS)


@app.route("/dealer")
@login_required
def dealer_home():
    """Dealer portal: raise a ticket + see only the queries they raised."""
    user = current_user()
    if user["role"] != "dealer":
        return redirect(url_for("home"))
    error = ""
    tickets = []
    try:
        ensure_tables()
        tickets = fetch_all(role="dealer")["tickets"]
    except Exception as e:
        error = str(e)
    sent = request.args.get("sent") == "1"
    return render_template("dealer.html", user=user, tickets=tickets, error=error, sent=sent, **ICONS)


@app.route("/add-ticket", methods=["POST"])
@login_required
def add_ticket():
    user = current_user()
    subject = (request.form.get("subject") or "").strip()
    requester = (request.form.get("requester") or "").strip()
    site = (request.form.get("site") or "").strip()
    channel = (request.form.get("channel") or "email").strip()
    priority = (request.form.get("priority") or "med").strip()
    # A dealer's ticket is tagged so it shows only in their view.
    raised_by = "Dealer" if user and user["role"] == "dealer" else None
    if subject and requester:
        try:
            cur = get_cursor()
            cur.execute(
                "INSERT INTO tickets (subject, requester, site, channel, priority, status, raised_by) VALUES (?,?,?,?,?,'open',?)",
                subject, requester, site, channel, priority, raised_by)
        except Exception:
            pass
    # Return to wherever the form was submitted from.
    if user and user["role"] == "dealer":
        return redirect(url_for("dealer_home", sent="1"))
    if request.form.get("from") == "help":
        return redirect(url_for("help_page", sent="1"))
    return redirect("/#contact")


@app.route("/help", methods=["GET"])
@login_required
def help_page():
    """A dedicated page housing the full ticketing form (staff only)."""
    user = current_user()
    if user["role"] == "dealer":
        return redirect(url_for("dealer_home"))
    sent = request.args.get("sent") == "1"
    return render_template("help.html", user=user, sent=sent, **ICONS)


@app.route("/add-contact", methods=["POST"])
@login_required
def add_contact():
    name = (request.form.get("name") or "").strip()
    dealer = (request.form.get("dealer") or "").strip()
    email = (request.form.get("email") or "").strip()
    if name:
        try:
            cur = get_cursor()
            cur.execute("INSERT INTO contacts (name, dealer, email) VALUES (?,?,?)", name, dealer, email)
        except Exception:
            pass
    return redirect("/#contacts")


@app.route("/add-action", methods=["POST"])
@login_required
def add_action():
    title = (request.form.get("title") or "").strip()
    due = (request.form.get("due") or "").strip()
    if title:
        try:
            cur = get_cursor()
            cur.execute("INSERT INTO actions (title, due, done) VALUES (?,?,0)", title, due)
        except Exception:
            pass
    return redirect("/#actions")


@app.route("/toggle-action", methods=["POST"])
@login_required
def toggle_action():
    action_id = request.form.get("id")
    if action_id:
        try:
            cur = get_cursor()
            # Flip the done flag for this row.
            cur.execute("UPDATE actions SET done = 1 - done WHERE id = ?", int(action_id))
        except Exception:
            pass
    return redirect("/#actions")


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
