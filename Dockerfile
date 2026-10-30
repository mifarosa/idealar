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
# Waitress discards X-Forwarded-Proto unless the sender is trusted; without it Django thinks every request is plain
# HTTP and builds http:// redirect URIs (Google sign-in rejects them). Safe to trust any peer: compose publishes the
# port on 127.0.0.1 only, so the sole client is the reverse proxy on the same host.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec waitress-serve --listen=0.0.0.0:8000 --trusted-proxy='*' --trusted-proxy-headers='x-forwarded-proto' config.wsgi:application"]
