FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Persistent data (database, recipe photos). On Railway, attach a Volume at /data.
ENV DATA_DIR=/data
ENV DATABASE_URL=sqlite:////data/dinner101.db
EXPOSE 8000
CMD ["sh", "-c", "mkdir -p /data && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
