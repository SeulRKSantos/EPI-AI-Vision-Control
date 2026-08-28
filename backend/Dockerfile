FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first: this layer is cached until pyproject.toml changes.
# The dev extras bring in pytest so the suite can run inside the container.
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

COPY alembic.ini .
COPY app/ ./app/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
