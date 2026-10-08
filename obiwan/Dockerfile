FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY obiwan ./obiwan
RUN uv sync --frozen --no-dev
ENV OBIWAN_DATA_DIR=/data OBIWAN_INBOX_DIR=/inbox
EXPOSE 8070
CMD ["uv", "run", "--no-dev", "--frozen", "uvicorn", "--factory", "obiwan.web:app_factory", "--host", "0.0.0.0", "--port", "8070"]
