# PDX Artifact Engine — private job runtime image.
#
# pip and setuptools are install-time only. They are uninstalled before the
# image is published so they are not part of the scanned runtime set.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDX_ENGINE_AUTH_PROFILE=self_hosted \
    PDX_ENGINE_CONTRACT_ROOT=/app/docs/phase0 \
    PDX_ENGINE_JOB_DB=/var/lib/pdx/jobs/jobs.sqlite3 \
    PDX_ENGINE_STAGING_ROOT=/var/lib/pdx/staging

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . \
    && pip uninstall -y pip setuptools \
    && useradd --system --uid 10002 --home /nonexistent --shell /usr/sbin/nologin pdx \
    && mkdir -p /var/lib/pdx/jobs /var/lib/pdx/staging \
    && chown -R pdx:pdx /var/lib/pdx

USER pdx
EXPOSE 8910
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8910/ready')"

CMD ["pdx-internal", "--host", "0.0.0.0", "--port", "8910"]
