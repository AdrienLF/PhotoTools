# Use Python base image with uv pre-installed and CUDA support
FROM ghcr.io/astral-sh/uv:python3.12-bookworm

# Install system dependencies including CUDA
RUN apt-get update && apt-get install -y \
    libsqlite3-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy configuration files
COPY pyproject.toml .

# Install dependencies with CUDA support
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r pyproject.toml

# Copy the application code
COPY sort_photos_ratio.py .

# Create a volume mount point
VOLUME /data

# Set environment variables for GPU support
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# Run the application
CMD ["python", "sort_photos_ratio.py", "--folder", "/data"]
