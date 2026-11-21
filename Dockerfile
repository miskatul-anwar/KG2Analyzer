# --- build the React UI -------------------------------------------------------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- FastAPI backend serving the API + built UI ----------------------------------
FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=ui /ui/dist /app/frontend/dist
ENV KG2A_TRANSLATOR=auto
EXPOSE 8000
CMD ["python", "-m", "kg2analyzer", "serve", "--host", "0.0.0.0", "--port", "8000", "--benchmark", "enterprise"]
