FROM nvidia/cuda:12.2.0-base-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pods
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

# Pre-download llama.cpp CUDA binaries
RUN mkdir -p /root/pods/llama.cpp/build/bin

# Runtime directories
RUN mkdir -p /root/.pods/logs /root/pods/models

EXPOSE 8080

ENTRYPOINT ["pods"]
CMD ["--help"]
