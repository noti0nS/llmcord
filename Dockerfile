FROM python:3.13-slim

ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY pyproject.toml uv.lock .
RUN pip install --no-cache-dir uv \
    && uv export --no-dev --no-hashes --format requirements.txt -o requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall uv -y

COPY llmcrd.py .
COPY src/ src/

CMD ["python", "llmcrd.py"]
