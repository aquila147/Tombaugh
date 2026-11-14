FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CACHE_DIR=/tmp/tombaugh-cache \
    PORT=8000

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Hugging Face Spaces runs containers as uid 1000
RUN useradd -m -u 1000 tombaugh
USER tombaugh

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
