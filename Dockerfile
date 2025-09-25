# Dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn eventlet

COPY . .
EXPOSE 5000

# Use eventlet worker for WebSocket support
CMD ["gunicorn", "-k", "eventlet", "-w", "1", "-b", "0.0.0.0:5000", "main:app"]
