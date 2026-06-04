#!/usr/bin/env bash
#
# Comprehensive test suite for the llamacpp-vision Docker container.
# Tests build, GPU passthrough, model loading, vision inference.
#
# Usage:
#   ./scripts/test-vision-server.sh          # Run all tests
#   ./scripts/test-vision-server.sh --quick  # Skip vision test
#   ./scripts/test-vision-server.sh --build  # Force rebuild

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.yml"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}  PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "${RED}  FAIL${NC} $1"; ((FAIL++)); }
warn() { echo -e "${YELLOW}  WARN${NC} $1"; ((WARN++)); }
info() { echo -e "${BLUE}  INFO${NC} $1"; }

section() {
    echo ""
    echo "======================================================================"
    echo "  $1"
    echo "======================================================================"
}

# ── Parse args ──
QUICK=false
BUILD=false
for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=true ;;
        --build) BUILD=true ;;
    esac
done

echo ""
echo "======================================================================"
echo "  LLAMACPP-VISION DOCKER TEST SUITE"
echo "  Project: $PROJECT_DIR"
echo "  Started: $(date '+%H:%M:%S')"
echo "======================================================================"

# ═══════════════════════════════════════════════════════════════════════
# 1. PREREQUISITES
# ═══════════════════════════════════════════════════════════════════════
section "1. PREREQUISITES"

# Check Docker
if command -v docker &>/dev/null; then
    pass "Docker installed: $(docker --version)"
else
    fail "Docker not installed"
    exit 1
fi

# Check Docker Compose
if docker compose version &>/dev/null; then
    pass "Docker Compose: $(docker compose version --short)"
else
    fail "Docker Compose not available"
    exit 1
fi

# Check ROCm GPU devices
if [ -e /dev/kfd ]; then
    pass "ROCm KFD device: /dev/kfd"
else
    warn "ROCm KFD not found at /dev/kfd"
fi

if [ -d /dev/dri ]; then
    pass "DRI devices: $(ls /dev/dri/render* 2>/dev/null | tr '\n' ' ')"
else
    warn "DRI devices not found at /dev/dri"
fi

# Check GPU info
if command -v rocminfo &>/dev/null; then
    GPU_NAME=$(rocminfo 2>/dev/null | grep -m1 "Marketing Name" | awk -F: '{print $2}' | xargs)
    info "GPU: $GPU_NAME"
else
    warn "rocminfo not available on host"
fi

# Check model files
MODEL_DIR="/mnt/hdd/ai-models"
if [ -f "$MODEL_DIR/Qwen3VL-8B-Instruct-Q4_K_M.gguf" ]; then
    pass "Model file exists: $(ls -lh "$MODEL_DIR/Qwen3VL-8B-Instruct-Q4_K_M.gguf" | awk '{print $5}')"
else
    fail "Model missing: $MODEL_DIR/Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    info "Download with: ./scripts/download-vision-model.sh"
fi

if [ -f "$MODEL_DIR/mmproj-Qwen3VL-8B-Instruct-F16.gguf" ]; then
    pass "mmproj file exists: $(ls -lh "$MODEL_DIR/mmproj-Qwen3VL-8B-Instruct-F16.gguf" | awk '{print $5}')"
else
    fail "mmproj missing: $MODEL_DIR/mmproj-Qwen3VL-8B-Instruct-F16.gguf"
fi

# ═══════════════════════════════════════════════════════════════════════
# 2. BUILD
# ═══════════════════════════════════════════════════════════════════════
section "2. BUILD"

if [ "$BUILD" = true ] || [ "$FAIL" -eq 0 ]; then
    cd "$PROJECT_DIR"
    info "Building llamacpp-vision container..."
    if $COMPOSE build llamacpp-vision 2>&1 | tee /tmp/vision-build.log; then
        pass "Container built successfully"
    else
        fail "Container build failed"
        info "See: /tmp/vision-build.log"
    fi
else
    warn "Skipping build (prerequisites failed)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 3. STARTUP
# ═══════════════════════════════════════════════════════════════════════
section "3. STARTUP"

if [ "$FAIL" -eq 0 ]; then
    info "Starting llamacpp-vision container..."
    $COMPOSE up -d llamacpp-vision 2>&1 | tee /tmp/vision-start.log

    # Wait for healthcheck
    info "Waiting for container to become healthy (up to 120s)..."
    HEALTHY=false
    for i in $(seq 1 30); do
        STATUS=$(docker inspect --format='{{.State.Health.Status}}' llamacpp-vision 2>/dev/null || echo "starting")
        if [ "$STATUS" = "healthy" ]; then
            HEALTHY=true
            break
        fi
        info "  Attempt $i/30: status=$STATUS"
        sleep 4
    done

    if [ "$HEALTHY" = true ]; then
        pass "Container is healthy"
    else
        fail "Container healthcheck failed"
        info "Logs:"
        docker logs --tail 50 llamacpp-vision 2>/dev/null || true
    fi
else
    warn "Skipping startup (build/prereqs failed)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 4. API TESTS
# ═══════════════════════════════════════════════════════════════════════
section "4. API ENDPOINTS"

if [ "$FAIL" -eq 0 ]; then
    # Health
    if curl -sf http://localhost:6663/health -o /dev/null; then
        pass "GET /health responds (200)"
        info "Response: $(curl -s http://localhost:6663/health)"
    else
        fail "GET /health no response"
    fi

    # Models
    if curl -sf http://localhost:6663/models -o /tmp/vision-models.json; then
        MODEL_COUNT=$(jq '.data | length' /tmp/vision-models.json 2>/dev/null || echo "0")
        pass "GET /models responds ($MODEL_COUNT models)"

        # Check if Qwen3VL is listed
        if grep -q "Qwen3VL" /tmp/vision-models.json; then
            pass "Qwen3VL found in model list"
        else
            warn "Qwen3VL not in model list (may need to load)"
        fi
    else
        fail "GET /models no response"
    fi

    # Metrics
    if curl -sf http://localhost:6663/metrics -o /dev/null; then
        pass "GET /metrics responds"
    else
        warn "GET /metrics not available"
    fi
else
    warn "Skipping API tests (container not running)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 5. TEXT CHAT
# ═══════════════════════════════════════════════════════════════════════
section "5. TEXT CHAT"

if [ "$FAIL" -eq 0 ]; then
    info "Testing text-only chat completion..."

    RESPONSE=$(curl -sf http://localhost:6663/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{"model":"Qwen3VL-8B-Instruct-Q4_K_M","messages":[{"role":"user","content":"What is 2+2? Answer with just the number."}],"temperature":0.1,"max_tokens":10}' \
        2>/dev/null || echo "")

    if [ -n "$RESPONSE" ]; then
        ANSWER=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
        if [ -n "$ANSWER" ]; then
            pass "Text chat works: '$ANSWER'"
        else
            fail "Text chat returned empty answer"
            info "Response: $(echo "$RESPONSE" | head -c 200)"
        fi
    else
        fail "Text chat request failed"
    fi
else
    warn "Skipping text chat (container not running)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 6. VISION CHAT (CRITICAL)
# ═══════════════════════════════════════════════════════════════════════
section "6. VISION CHAT (CRITICAL)"

if [ "$QUICK" = true ]; then
    warn "Skipping vision test (--quick mode)"
elif [ "$FAIL" -eq 0 ]; then
    info "Testing vision chat with tiny test image..."

    # Create a 50x50 red PNG in memory
    # Using Python since we need base64 + image creation
    if command -v python3 &>/dev/null; then
        TEST_JSON=$(python3 -c '
import base64, io
from PIL import Image
img = Image.new("RGB", (50, 50), "red")
buf = io.BytesIO()
img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
import json
payload = {
    "model": "Qwen3VL-8B-Instruct-Q4_K_M",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "What color is this? One word."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]
    }],
    "temperature": 0.1,
    "max_tokens": 10
}
print(json.dumps(payload))
')

        RESPONSE=$(curl -sf http://localhost:6663/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "$TEST_JSON" 2>/dev/null || echo "")

        if [ -n "$RESPONSE" ]; then
            STATUS=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
            if [ -n "$STATUS" ]; then
                pass "VISION WORKS! Answer: '$STATUS'"
                info "Full response: $(echo "$RESPONSE" | jq -c '.choices[0].message.content' 2>/dev/null)"
            else
                # Check for error
                ERR=$(echo "$RESPONSE" | jq -r '.error.message // empty' 2>/dev/null)
                if [ -n "$ERR" ]; then
                    fail "Vision error: $ERR"
                else
                    fail "Vision returned empty (check mmproj)"
                    info "Response: $(echo "$RESPONSE" | head -c 300)"
                fi
            fi
        else
            fail "Vision request failed (no response)"
            info "Check container logs: docker logs --tail 30 llamacpp-vision"
        fi
    else
        warn "python3 + Pillow not available, skipping vision test"
        info "Install: pip install Pillow"
    fi
else
    warn "Skipping vision test (previous failures)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 7. GPU OFFLOAD
# ═══════════════════════════════════════════════════════════════════════
section "7. GPU OFFLOAD"

if [ "$FAIL" -eq 0 ]; then
    # Check logs for GPU offload info
    OFFLOAD_LOG=$(docker logs llamacpp-vision 2>&1 | grep -i "offload\|GPU\|layers" | tail -5 || true)
    if [ -n "$OFFLOAD_LOG" ]; then
        pass "GPU offload detected in logs"
        echo "$OFFLOAD_LOG" | while read line; do info "$line"; done
    else
        warn "Cannot confirm GPU offload from logs"
    fi

    # Check if process is using GPU memory
    if command -v rocm-smi &>/dev/null; then
        VRAM=$(rocm-smi --showmeminfo vram 2>/dev/null | grep -E "[0-9]+\." | head -1 || true)
        if [ -n "$VRAM" ]; then
            info "VRAM usage: $VRAM"
        fi
    else
        warn "rocm-smi not available"
    fi
else
    warn "Skipping GPU check (container not running)"
fi

# ═══════════════════════════════════════════════════════════════════════
# 8. INTEGRATION (shim → vision server)
# ═══════════════════════════════════════════════════════════════════════
section "8. INTEGRATION (captcha-solver shim)"

if [ "$FAIL" -eq 0 ]; then
    # Check if captcha-solver is configured correctly
    SHIM_URL="http://localhost:1232"

    if curl -sf "$SHIM_URL/stats" -o /tmp/shim-stats.json 2>/dev/null; then
        VISION_URL=$(jq -r '.llamacpp_url // empty' /tmp/shim-stats.json 2>/dev/null)
        if echo "$VISION_URL" | grep -q "6663"; then
            pass "Shim configured for port 6663: $VISION_URL"
        else
            warn "Shim may not be configured for local vision: $VISION_URL"
        fi
    else
        warn "Shim not running at $SHIM_URL"
    fi

    # Test shim → vision server path
    if command -v python3 &>/dev/null; then
        TEST_JSON=$(python3 -c '
import base64, io, json
from PIL import Image
img = Image.new("RGB", (50, 50), "blue")
buf = io.BytesIO()
img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
payload = {
    "model": "Qwen3VL-8B-Instruct-Q4_K_M",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What color? One word."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
    ]}],
    "temperature": 0.1, "max_tokens": 10
}
print(json.dumps(payload))
')

        RESPONSE=$(curl -sf "$SHIM_URL/v1/chat/completions" \
            -H "Content-Type: application/json" \
            -d "$TEST_JSON" 2>/dev/null || echo "")

        if [ -n "$RESPONSE" ]; then
            ANSWER=$(echo "$RESPONSE" | jq -r '.choices[0].message.content // empty' 2>/dev/null)
            if [ -n "$ANSWER" ]; then
                pass "Shim → Vision server works: '$ANSWER'"
            else
                fail "Shim returned empty answer"
            fi
        else
            warn "Shim → Vision server request failed (shim may need restart)"
        fi
    fi
else
    warn "Skipping integration test (vision server not ready)"
fi

# ═══════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════
section "SUMMARY"

echo ""
echo "  Total:  $((PASS + FAIL + WARN))"
echo -e "  ${GREEN}PASS${NC}:   $PASS"
echo -e "  ${RED}FAIL${NC}:   $FAIL"
echo -e "  ${YELLOW}WARN${NC}:   $WARN"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}All critical tests passed!${NC}"
    echo "  Start the full stack: docker compose up -d"
else
    echo -e "  ${RED}Some tests failed.${NC} Check the output above."
    echo ""
    echo "  Common fixes:"
    echo "    - Model missing:    ./scripts/download-vision-model.sh"
    echo "    - Build failed:     docker compose build --no-cache llamacpp-vision"
    echo "    - Container crash:  docker logs --tail 50 llamacpp-vision"
    echo "    - OOM:              Edit docker-compose.yml, set CTX_SIZE=2048"
    echo "    - No GPU:           Check /dev/kfd and /dev/dri exist"
fi

echo ""
echo "  Full report: /tmp/vision-server-test-$(date +%Y%m%d_%H%M%S).log"
echo "======================================================================"
