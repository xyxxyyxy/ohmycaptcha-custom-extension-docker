# llama.cpp vision server with ROCm/HIP for AMD GPUs
# Usage: docker compose up -d llamacpp-vision
#
# For RX 6600 (gfx1032) 8GB VRAM:
#   - Loads Qwen3VL-8B-Instruct-Q4_K_M (~5GB)
#   - Loads mmproj (~2GB)
#   - Total: ~7GB of 8GB VRAM
#
# If OOM: reduce --ctx-size in docker-compose.yml

FROM rocm/dev-ubuntu-22.04:6.2.4

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies + ROCm development libraries
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    build-essential \
    python3-pip \
    hipblas-dev \
    rocblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone llama.cpp (pinned to recent stable version)
WORKDIR /build
RUN git clone --depth 1 --branch b4621 https://github.com/ggml-org/llama.cpp.git

# Build with HIP/ROCm support for AMD GPUs
# Quote AMDGPU_TARGETS to prevent shell from interpreting semicolons
WORKDIR /build/llama.cpp
RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_HIP=ON \
    -DAMDGPU_TARGETS="gfx1032" \
    && cmake --build build --config Release -j$(nproc)

# Runtime stage
FROM rocm/dev-ubuntu-22.04:6.2.4

ENV DEBIAN_FRONTEND=noninteractive

# Install runtime deps only
RUN apt-get update && apt-get install -y \
    libgomp1 \
    hipblas \
    rocblas \
    && rm -rf /var/lib/apt/lists/*

# Copy built binary
COPY --from=0 /build/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

# Expose API port
EXPOSE 6663

# Environment for AMD GPU support
ENV HSA_OVERRIDE_GFX_VERSION=10.3.0
ENV HIP_VISIBLE_DEVICES=0

# Models mounted from host at runtime
VOLUME ["/models"]

# Default: Qwen3VL Q4_K_M on port 6663
# Override via docker-compose environment
ENV MODEL_PATH=/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf
ENV MMPROJ_PATH=/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf
ENV NGL=99
ENV CTX_SIZE=4096
ENV BATCH_SIZE=512
ENV UBATCH_SIZE=128

ENTRYPOINT ["llama-server"]
CMD ["-m", "/models/Qwen3-VL-8B-Instruct-Q4_K_M.gguf", \
     "--mmproj", "/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf", \
     "-ngl", "99", \
     "--port", "6663", \
     "--host", "0.0.0.0", \
     "--ctx-size", "4096", \
     "--batch-size", "512", \
     "--ubatch-size", "128", \
     "-fa", \
     "--timeout", "300", \
     "--metrics"]