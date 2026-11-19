FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SENT_FILE=/data/sent.json

WORKDIR /app
COPY requirements.txt requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# sent.json из репозитория кладётся в образ как «семя»: на первом старте копируется в том /data
COPY *.py keywords.txt sent.json ./
RUN mkdir -p /data

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# Один процесс, без --workers: от двойного запуска ленты защищает блокировка в памяти
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
