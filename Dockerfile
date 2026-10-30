FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATABASE_PATH=/app/data/space_trader.sqlite3

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Непривилегированный пользователь; data/ принадлежит ему, чтобы именованный том унаследовал права.
RUN useradd --create-home --uid 1000 bot && mkdir -p /app/data && chown bot:bot /app/data

COPY --chown=bot:bot . .

USER bot
VOLUME ["/app/data"]

CMD ["python", "main.py"]
