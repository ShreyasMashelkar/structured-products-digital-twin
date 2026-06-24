# Single-image deploy of the SPDT React desk: build the Vite/React frontend, then serve
# it together with the FastAPI engine from one uvicorn process (same-origin /api).
# Targets Hugging Face Spaces (Docker SDK), which expects the app on port 7860.

# ---- stage 1: build the React frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/webapp/frontend
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build

# ---- stage 2: python runtime serving API + built SPA ----
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860
WORKDIR /app

COPY webapp/requirements.txt ./webapp/requirements.txt
RUN pip install --no-cache-dir -r webapp/requirements.txt

# engine source + server (the seam imports integration -> xva, so both are needed)
COPY spdt/ ./spdt/
COPY integration/ ./integration/
COPY xva/ ./xva/
COPY webapp/ ./webapp/

# built frontend from stage 1 (overlays the source tree's empty dist)
COPY --from=frontend /app/webapp/frontend/dist ./webapp/frontend/dist

EXPOSE 7860
CMD ["sh", "-c", "uvicorn webapp.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
