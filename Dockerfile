FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 incident \
    && useradd --uid 10001 --gid incident --no-create-home incident \
    && mkdir /app/uploads \
    && chown incident:incident /app/uploads
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
USER incident
EXPOSE 8000
CMD ["python", "-m", "app.container"]
