# Pin to Debian 12 (bookworm) - the version Microsoft's ODBC driver supports
# cleanly. (Plain python:3.12-slim now points at Debian 13, whose stricter
# signature checking rejects the Microsoft repo, so we pin explicitly.)
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install the Microsoft ODBC Driver 18 for SQL Server.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gnupg unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
    && sed -i 's#deb #deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] #' \
        /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2"]
