"""
The entire test app: one page that says hello.
No database, nothing clever. Its only job is to prove that a push to
GitHub ends up as a live page in Azure.
"""
import os
from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    # A version string so you can SEE a new deploy land. Bump it, push,
    # and watch the number change on the live site.
    version = os.environ.get("APP_VERSION", "2")
    return f"""
    <!doctype html>
    <html lang="en-GB">
    <head>
      <meta charset="utf-8">
      <title>Compas deploy test</title>
      <style>
        body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
               background:#1B2A5B; color:#fff; display:grid; place-items:center;
               height:100vh; margin:0; text-align:center; }}
        .v {{ font-size:64px; font-weight:700; letter-spacing:-2px; }}
        .l {{ color:#9fb0d9; font-size:15px; margin-top:8px; }}
        .dot {{ width:12px; height:12px; border-radius:50%; background:#C8102E;
               display:inline-block; margin-right:8px; }}
      </style>
    </head>
    <body>
      <div>
        <div><span class="dot"></span>Compas deploy test</div>
        <div class="v">Version {version}</div>
        <div class="l">If you can read this, the pipeline works.</div>
      </div>
    </body>
    </html>
    """


@app.route("/health")
def health():
    # Azure pings this to check the app is alive.
    return {"status": "ok"}


if __name__ == "__main__":
    # Local testing only. Azure uses gunicorn (see Dockerfile).
    app.run(host="0.0.0.0", port=8000, debug=True)
