# One service: FastAPI serves the search API and the built frontend.

FROM node:26-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HF_HOME=/app/hf PATH=/app/backend/.venv/bin:$PATH
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen
COPY backend/ ./
COPY data/ /app/data/
# Railway checks out LFS files as pointers; fetch them for the commit being built.
ARG RAILWAY_GIT_COMMIT_SHA
RUN python fetch_lfs.py data/index/vectors.npy
# Bake the pinned query model into the image so startup never touches the Hub.
RUN python -c "from huggingface_hub import snapshot_download; from pipeline.projects import QUERY_MODEL, QUERY_MODEL_REVISION; snapshot_download(QUERY_MODEL, revision=QUERY_MODEL_REVISION)"
ENV HF_HUB_OFFLINE=1
# torch otherwise starts a thread per host core, far more than the service's CPU limit.
ENV OMP_NUM_THREADS=4
COPY --from=frontend /app/frontend/dist /app/frontend/dist
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
