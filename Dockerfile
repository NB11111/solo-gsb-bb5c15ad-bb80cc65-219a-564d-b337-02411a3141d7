FROM python:3.11-slim

# Do not buffer logs, do not write .pyc files in the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so Docker can cache this layer independently
# from application code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and startup wrapper
COPY app ./app

# Run as the non-root user shipped with the slim image
USER nobody

EXPOSE 8000

# Dependency installation is part of the image build above; the container
# starts the API directly (no separate init step required).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
