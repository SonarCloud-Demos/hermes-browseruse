# Optional extra CA certificates (e.g. a corporate TLS-inspecting proxy).
# Empty by default; override with a build context named "extra-ca" that
# contains *.crt files (see README, "Behind a TLS-inspecting proxy").
FROM scratch AS extra-ca

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANONYMIZED_TELEMETRY=false \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Unprivileged runtime user; Chromium reads its NSS trust store from $HOME/.pki.
RUN useradd --create-home --uid 1000 app

COPY --from=extra-ca / /usr/local/share/ca-certificates/extra/
RUN if ls /usr/local/share/ca-certificates/extra/*.crt >/dev/null 2>&1; then \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates libnss3-tools \
        && update-ca-certificates \
        && mkdir -p /home/app/.pki/nssdb && certutil -d sql:/home/app/.pki/nssdb -N --empty-password \
        && for c in /usr/local/share/ca-certificates/extra/*.crt; do \
             certutil -d sql:/home/app/.pki/nssdb -A -t "C,," -n "$(basename "$c")" -i "$c"; done \
        && chown -R app:app /home/app/.pki \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Only takes effect when the bundle has extra CAs; otherwise it is the stock bundle.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# requirements.lock: requirements.txt resolved with hashes
# (uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes -o requirements.lock)
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements.lock \
    && playwright install --with-deps chromium

COPY server.py .

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
