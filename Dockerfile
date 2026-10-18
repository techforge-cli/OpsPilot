FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

RUN useradd -m -r opspilot && mkdir -p /var/lib/opspilot /etc/opspilot && chown -R opspilot:opspilot /var/lib/opspilot /etc/opspilot
USER opspilot

ENV OPSPILOT_DATA_DIR=/var/lib/opspilot
ENV OPSPILOT_BIND_HOST=0.0.0.0
ENV OPSPILOT_BIND_PORT=8443

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8443/healthz')"

ENTRYPOINT ["opspilot"]
