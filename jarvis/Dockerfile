FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY jarvis ./jarvis
RUN uv sync --frozen --no-dev
ENV JARVIS_DATA_DIR=/data
EXPOSE 8090
CMD ["uv", "run", "--no-dev", "uvicorn", "--factory", "jarvis.web:app_factory", "--host", "0.0.0.0", "--port", "8090"]
