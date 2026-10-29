# ---- 1. build the React frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python API serving the API + the built frontend
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860
RUN useradd -m -u 1000 app
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/contracts/ data/contracts/
COPY --from=web /web/dist frontend/dist
RUN chown -R app:app /app
USER app
WORKDIR /app/backend
EXPOSE 7860
CMD ["sh", "-c", "uvicorn claimcheck.api:app --host 0.0.0.0 --port ${PORT}"]
