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

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies + ROCm libraries
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    build-essential \
    python3-pip \
    hipblas-dev \
    rocblas-dev \
    hipblas \
    rocblas \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Clone llama.cpp (use master for vision server support)
# b4621 was too old --mmproj only worked with llava-cli, not server
WORKDIR /build
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git

# Patch: ROCm 6.2 lacks __hip_fp8_e4m3 (added in ROCm 6.3).
# Use separate script to avoid Dockerfile multi-line parsing issues.
COPY patch-rocm.sh /tmp/patch-rocm.sh
RUN bash /tmp/patch-rocm.sh

# Build with HIP/ROCm support for AMD GPUs
WORKDIR /build/llama.cpp
RUN cmake -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_HIP=ON \
    -DAMDGPU_TARGETS="gfx1032" \
    && cmake --build build --config Release -j$(nproc)

# Make shared libs findable and symlink binary to PATH
RUN echo "/build/llama.cpp/build/lib" > /etc/ld.so.conf.d/llama.conf \
    && ldconfig \
    && ln -s /build/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

# Expose API port
EXPOSE 6663

# Environment for AMD GPU support
ENV HSA_OVERRIDE_GFX_VERSION=10.3.0
ENV HIP_VISIBLE_DEVICES=0
ENV LD_LIBRARY_PATH="/build/llama.cpp/build/lib:${LD_LIBRARY_PATH}"

# Models mounted from host at runtime
VOLUME ["/models"]

ENTRYPOINT ["llama-server"]
CMD ["-m", "/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf", \
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
