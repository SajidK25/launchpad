FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/workspace/apps/api

WORKDIR /workspace

COPY requirements.lock pyproject.toml ./
RUN python -m pip install --no-deps --requirement requirements.lock

COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

CMD ["python", "--version"]
