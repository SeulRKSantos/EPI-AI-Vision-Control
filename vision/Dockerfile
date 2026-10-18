FROM python:3.12-slim

# libgl1 / libglib: OpenCV needs them to decode camera frames.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Live view for the panel: MJPEG stream and detection JSON.
EXPOSE 8081

CMD ["python", "inference_worker.py"]
