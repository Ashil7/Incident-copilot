FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/pip install -r /tmp/requirements.txt

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
RUN groupadd --gid 10001 incident \
    && useradd --uid 10001 --gid incident --no-create-home incident \
    && mkdir /app/uploads \
    && chown incident:incident /app/uploads
COPY --chown=incident:incident app ./app
COPY --chown=incident:incident scripts ./scripts
COPY --chown=incident:incident alembic.ini ./
USER incident
EXPOSE 8000
CMD ["python", "-m", "app.container"]
