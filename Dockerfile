# Now needs the Microsoft ODBC driver so pyodbc can talk to SQL Server.
# This is the same driver setup the real Compas app uses.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install the Microsoft ODBC Driver 18 for SQL Server.
# Note: this base image is Debian 13, so we use the debian/13 package list.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gnupg unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/13/prod.list \
        | tee /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2"]
