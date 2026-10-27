# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV LAYA_WEB_DIR=/app/web LAYA_TOKENS_FILE=/data/tokens.json PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models LAYA_HOST=0.0.0.0
WORKDIR /app

# CPU-only torch first, so pip does not pull the CUDA/Triton wheels.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY pyproject.toml ./
COPY src ./src
COPY web ./web
RUN pip install .
RUN python -c "import torch; assert torch.version.cuda is None and torch.version.hip is None, 'CPU-only torch required'"

EXPOSE 9120
CMD ["python", "-m", "laya_service.app"]
