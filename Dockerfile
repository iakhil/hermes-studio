# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend
FROM python:3.11-slim
WORKDIR /app

# Install uv
RUN pip install uv

# Install hermes-agent
RUN pip install hermes-agent

# Copy backend
COPY backend/ ./backend/
WORKDIR /app/backend
RUN uv pip install --system -e .

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./static/

EXPOSE 8420

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
