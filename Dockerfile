# The page (TypeScript, built by Vite) and the API server (Python, run with uv) in one image.
# The server serves both from one port; see "Deploying" in README.md.

# ---------- build the page into dist/ ----------
FROM node:22-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.base.json tsconfig.json vite.config.ts ./
COPY web ./web
# Only the Vite build: `npm run build` also typechecks against the Python server, which this stage
# doesn't have. The deploy workflow runs the full checks before building.
RUN npx vite build

# ---------- the server ----------
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY server ./server
COPY --from=web /app/dist ./dist

# DATA_DIR is a persistent volume in production (fly.toml mounts one at /data).
ENV PATH=/opt/venv/bin:$PATH HOST=0.0.0.0 PORT=8080 DATA_DIR=/data STATIC_DIR=/app/dist
EXPOSE 8080
CMD ["python", "-m", "server"]
