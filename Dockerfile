FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVIDENCEGRAPH_ENV=production \
    EVIDENCEGRAPH_DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 evidencegraph
COPY backend ./backend
COPY frontend ./frontend
COPY datasets ./datasets
RUN mkdir -p /app/data && chown -R evidencegraph:evidencegraph /app
USER evidencegraph
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import os; from urllib.request import Request, urlopen; host=os.getenv('EVIDENCEGRAPH_ALLOWED_HOSTS', 'localhost').split(',')[0].strip(); port=os.getenv('PORT', '8000'); urlopen(Request(f'http://127.0.0.1:{port}/api/v1/health/ready', headers={'Host': host}), timeout=3)"]
CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1"]
