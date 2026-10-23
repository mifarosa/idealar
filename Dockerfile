FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user; /data holds the SQLite file (a Docker volume).
RUN useradd --create-home --uid 1000 idealar && mkdir /data && chown idealar /data
COPY --chown=idealar . .
USER idealar

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/offline/', timeout=4)"

# Apply migrations on every start, then serve. `exec` lets waitress receive stop signals.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec waitress-serve --listen=0.0.0.0:8000 config.wsgi:application"]
