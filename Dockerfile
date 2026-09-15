# A tiny container. Python, the app, and gunicorn to serve it.
# No database driver here because this test app has no database.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Container Apps sends web traffic to this port.
EXPOSE 8000

# gunicorn runs the app in production (app.py -> variable named "app").
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2"]
