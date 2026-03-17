FROM python:3.11-slim

# Build deps for sqlite-vec native extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Explicit data directory for pip-installed package
ENV DATA_DIR=/app/data

# Copy project files
COPY pyproject.toml ./
COPY src/ src/
COPY app.py chainlit.md README.md ./
COPY .chainlit/ .chainlit/
COPY public/ public/
COPY data/ data/

# Install the package and all dependencies
RUN pip install --no-cache-dir .

EXPOSE 7860

CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "7860"]
