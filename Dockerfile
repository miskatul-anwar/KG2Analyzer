# --- build the React UI -------------------------------------------------------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- FastAPI backend serving the API + built UI ----------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=ui /ui/dist /app/frontend/dist
ENV KG2A_TRANSLATOR=auto
EXPOSE 8000
# KGs: mount them and pass --kgs, e.g. docker run -p 8000:8000 -v "$PWD/my_kgs:/data" kg2analyzer --kgs /data
ENTRYPOINT ["uv", "run", "--no-sync", "kg2analyzer", "serve", "--host", "0.0.0.0", "--port", "8000"]
