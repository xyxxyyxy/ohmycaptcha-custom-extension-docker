#!/usr/bin/env bash
#
# Master test runner for the CAPTCHA solving stack.
# Runs all tests in sequence and generates a comprehensive report.
#
# Usage:
#   ./run-all-tests.sh              # Run all tests
#   ./run-all-tests.sh --quick      # Skip browser-based e2e tests
#   ./run-all-tests.sh --e2e-only   # Only run e2e tests against demo sites
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

QUICK_MODE=false
E2E_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --quick) QUICK_MODE=true ;;
        --e2e-only) E2E_ONLY=true ;;
    esac
done

REPORT_FILE="/tmp/captcha-test-report-$(date +%Y%m%d_%H%M%S).log"
PASS_COUNT=0
FAIL_COUNT=0

# ── Color output ──
GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
BLUE='\033[94m'
RESET='\033[0m'

section() {
    echo ""
    echo -e "${BLUE}$(printf '=%.0s' {1..70})${RESET}"
    echo -e "${BLUE}  $1${RESET}"
    echo -e "${BLUE}$(printf '=%.0s' {1..70})${RESET}"
    echo ""
}

pass() {
    echo -e "${GREEN}  [PASS]${RESET} $1"
    ((PASS_COUNT++)) || true
}

fail() {
    echo -e "${RED}  [FAIL]${RESET} $1"
    ((FAIL_COUNT++)) || true
}

warn() {
    echo -e "${YELLOW}  [WARN]${RESET} $1"
}

info() {
    echo "  [INFO] $1"
}

# ── Test 1: Docker containers ──
test_containers() {
    section "TEST 1: Docker Containers"

    local containers=("llamacpp-vision" "captcha-solver" "whisper" "captcha-bridge")
    for c in "${containers[@]}"; do
        if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
            pass "Container $c is running"
        else
            fail "Container $c is NOT running"
            info "  Fix: docker compose up -d $c"
        fi
    done
}

# ── Test 2: Port checks ──
test_ports() {
    section "TEST 2: Port Listeners"

    local ports=("6663:Vision Server" "1232:Captcha Solver Shim" "1231:Captcha Bridge" "1233:Whisper" "8191:FlareSolverr")
    for entry in "${ports[@]}"; do
        local port="${entry%%:*}"
        local name="${entry#*:}"
        if nc -z localhost "$port" 2>/dev/null; then
            pass "$name (port $port) is listening"
        else
            fail "$name (port $port) is NOT reachable"
        fi
    done
}

# ── Test 3: Vision server direct ──
test_vision_server() {
    section "TEST 3: Local Vision Server (port 6663)"

    # Health check
    if curl -sf http://localhost:6663/health >/dev/null 2>&1; then
        pass "Health endpoint responding"
    else
        fail "Health endpoint not responding"
        info "Check: docker logs -f llamacpp-vision"
        return 1
    fi

    # Models check
    if curl -sf http://localhost:6663/models >/dev/null 2>&1; then
        pass "/models endpoint responding"
    else
        fail "/models endpoint not responding"
    fi

    # Vision chat test
    info "Testing vision chat with a red square image..."
    local result
    result=$(python3 -c '
import base64, io, json, urllib.request
from PIL import Image
img = Image.new("RGB", (50, 50), "red")
buf = io.BytesIO()
img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
payload = json.dumps({
    "model": "Qwen3VL-8B-Instruct-Q4_K_M",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What color is this? One word."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
    ]}],
    "max_tokens": 10
}).encode()
try:
    req = urllib.request.Request("http://localhost:6663/v1/chat/completions",
        data=payload, headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read())
    answer = data["choices"][0]["message"]["content"]
    print(f"OK: {answer}")
except Exception as e:
    print(f"FAIL: {e}")
')
    if echo "$result" | grep -q "^OK:"; then
        pass "Vision chat working: $(echo "$result" | sed 's/^OK: //')"
    else
        fail "Vision chat failed: $(echo "$result" | sed 's/^FAIL: //')"
        info "The vision server is running but vision chat failed."
        info "Common causes:"
        info "  1. Wrong model loaded (check docker logs llamacpp-vision | grep 'model')"
        info "  2. Missing mmproj file (check docker logs llamacpp-vision | grep mmproj)"
        info "  3. Out of GPU memory (reduce ctx-size in docker-compose.yml)"
    fi
}

# ── Test 4: Captcha Solver Shim ──
test_shim() {
    section "TEST 4: Captcha Solver Shim (port 1232)"

    if curl -sf http://localhost:1232/stats >/dev/null 2>&1; then
        pass "Shim /stats endpoint responding"

        local shim_info
        shim_info=$(curl -sf http://localhost:1232/stats 2>/dev/null)
        info "Shim URL: $(echo "$shim_info" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("llamacpp_url","?"))' 2>/dev/null || echo "?")"
        info "Model: $(echo "$shim_info" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("vision_model","?"))' 2>/dev/null || echo "?")"
    else
        fail "Shim not responding"
        info "Fix: docker compose up -d captcha-solver"
        info "Check: docker logs captcha-solver"
    fi
}

# ── Test 5: Captcha Bridge ──
test_bridge() {
    section "TEST 5: Captcha Bridge (port 1231)"

    if curl -sf http://localhost:1231/api/v1/health >/dev/null 2>&1; then
        pass "Bridge health endpoint responding"

        local bridge_info
        bridge_info=$(curl -sf http://localhost:1231/api/v1/health 2>/dev/null)
        info "Supported types: $(echo "$bridge_info" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(", ".join(d.get("supported_task_types",[])))' 2>/dev/null || echo "?")"
    else
        fail "Bridge not responding"
        info "Fix: docker compose up -d captcha-bridge"
        info "Check: docker logs captcha-bridge"
    fi
}

# ── Test 6: Brave CDP ──
test_brave_cdp() {
    section "TEST 6: Brave CDP (port 9222)"

    if curl -sf http://localhost:9222/json/version >/dev/null 2>&1; then
        pass "Brave CDP responding"

        local cdp_info
        cdp_info=$(curl -sf http://localhost:9222/json/version 2>/dev/null)
        info "Browser: $(echo "$cdp_info" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("Browser","?"))' 2>/dev/null || echo "?")"
    else
        fail "Brave CDP not responding"
        info "Fix: Run start-brave.sh or systemctl --user start brave-cdp"
    fi
}

# ── Test 7: Whisper ──
test_whisper() {
    section "TEST 7: Whisperfile (port 1233)"

    # Whisperfile only accepts POST to /v1/audio/transcriptions.
    # A GET returns 404, which means the server IS running.
    # Try POST with no file to get a meaningful error (should be 422 or similar).
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        http://localhost:1233/v1/audio/transcriptions 2>/dev/null || echo "000")
    if [ "$status" = "422" ] || [ "$status" = "400" ] || [ "$status" = "500" ] || [ "$status" = "405" ] || [ "$status" = "200" ]; then
        pass "Whisperfile responding (HTTP $status)"
    else
        # Fallback: check if port is open at all
        if nc -z localhost 1233 2>/dev/null; then
            pass "Whisperfile port is open (server running)"
        else
            fail "Whisperfile not responding (HTTP $status)"
            info "Fix: docker compose up -d whisper"
            info "Check: docker logs whisper"
        fi
    fi
}

# ── Test 8: E2E hCaptcha against demo site ──
test_e2e_hcaptcha() {
    section "TEST 8: E2E hCaptcha Demo (https://accounts.hcaptcha.com/demo)"
    info "This test creates a task via the bridge, which controls Brave via CDP"
    info "to solve the hCaptcha. The full pipeline:"
    info "  Bridge → CDP → Brave → checkbox → challenge → screenshot →"
    info "  Vision model → tile click → verify → token"
    info ""

    info "Creating task via bridge API..."
    local task_result
    task_result=$(curl -sf -X POST http://localhost:1231/createTask \
        -H "Content-Type: application/json" \
        -d '{
            "clientKey": "local",
            "task": {
                "type": "HCaptchaTaskProxyless",
                "websiteURL": "https://accounts.hcaptcha.com/demo",
                "websiteKey": "10000000-ffff-ffff-ffff-000000000001"
            }
        }' 2>/dev/null || echo '{"errorId":1,"errorDescription":"Bridge not responding"}')

    local error_id
    error_id=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorId",1))' 2>/dev/null || echo "1")

    if [ "$error_id" != "0" ]; then
        local err_desc
        err_desc=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorDescription","unknown"))' 2>/dev/null || echo "unknown")
        fail "Task creation failed: $err_desc"
        return 1
    fi

    local task_id
    task_id=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("taskId",""))' 2>/dev/null || echo "")
    pass "Task created: ${task_id:0:8}..."

    # Poll for result (hCaptcha can take 60-180 seconds to solve)
    local MAX_WAIT=180
    info "Polling for result (max ${MAX_WAIT}s - hCaptcha solving takes time)..."
    local start_time=$SECONDS
    local dots=0
    while [ $((SECONDS - start_time)) -lt $MAX_WAIT ]; do
        local result
        result=$(curl -sf -X POST http://localhost:1231/getTaskResult \
            -H "Content-Type: application/json" \
            -d "{\"clientKey\": \"local\", \"taskId\": \"$task_id\"}" 2>/dev/null || echo '{"status":"error"}')

        local status
        status=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","unknown"))' 2>/dev/null || echo "unknown")

        if [ "$status" = "ready" ]; then
            local token
            token=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("solution",{}).get("gRecaptchaResponse",""))' 2>/dev/null || echo "")
            if [ "${#token}" -gt 20 ]; then
                pass "Token obtained (len=${#token})"
                info "Token preview: ${token:0:60}..."
                return 0
            else
                fail "Empty token in ready response"
                return 1
            fi
        elif [ "$status" = "failed" ]; then
            local err
            err=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorDescription","unknown"))' 2>/dev/null || echo "unknown")
            fail "Task failed: $err"
            info "Check bridge logs: docker logs --tail 50 captcha-bridge"
            return 1
        fi

        # Progress indicator every 30 seconds
        if [ $(( (SECONDS - start_time) % 30 )) -eq 0 ] && [ $((SECONDS - start_time)) -gt 0 ]; then
            local elapsed=$((SECONDS - start_time))
            info "Still processing... (${elapsed}s elapsed)"
            info "  Bridge logs: docker logs --tail 10 captcha-bridge"
        fi
        echo -n "."
        sleep 3
    done

    fail "Timeout waiting for result (>${MAX_WAIT}s)"
    info "The solver timed out. Common causes:"
    info "  1. Vision model failed to analyze the challenge screenshot"
    info "  2. The challenge was too difficult (blurry/ambiguous images)"
    info "  3. Bot detection blocked the automation"
    info ""
    info "Diagnostics:"
    info "  docker logs --tail 50 captcha-bridge"
    info "  docker logs --tail 20 llamacpp-vision"
    return 1
}

# ── Test 9: E2E reCAPTCHA v2 against demo site ──
test_e2e_recaptcha() {
    section "TEST 9: E2E reCAPTCHA v2 Demo (https://www.google.com/recaptcha/api2/demo)"
    info "This test creates a task via the bridge, which controls Brave via CDP"
    info "to solve reCAPTCHA v2 via the audio challenge path. The pipeline:"
    info "  Bridge → CDP → Brave → checkbox → audio challenge → download →"
    info "  Whisper transcribe → submit answer → token"
    info ""
    warn "NOTE: reCAPTCHA v2 audio often triggers bot detection."
    warn "      If this test fails with 'automated queries', try:"
    warn "      - Using a residential proxy"
    warn "      - Waiting a few hours between attempts"
    warn "      - Using a different browser profile"
    info ""

    info "Creating task via bridge API..."
    local task_result
    task_result=$(curl -sf -X POST http://localhost:1231/createTask \
        -H "Content-Type: application/json" \
        -d '{
            "clientKey": "local",
            "task": {
                "type": "RecaptchaV2TaskProxyless",
                "websiteURL": "https://www.google.com/recaptcha/api2/demo",
                "websiteKey": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-"
            }
        }' 2>/dev/null || echo '{"errorId":1,"errorDescription":"Bridge not responding"}')

    local error_id
    error_id=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorId",1))' 2>/dev/null || echo "1")

    if [ "$error_id" != "0" ]; then
        local err_desc
        err_desc=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorDescription","unknown"))' 2>/dev/null || echo "unknown")
        fail "Task creation failed: $err_desc"
        return 1
    fi

    local task_id
    task_id=$(echo "$task_result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("taskId",""))' 2>/dev/null || echo "")
    pass "Task created: ${task_id:0:8}..."

    # Poll for result (reCAPTCHA v2 audio can take 60-180 seconds)
    local MAX_WAIT=180
    info "Polling for result (max ${MAX_WAIT}s - reCAPTCHA audio solving takes time)..."
    local start_time=$SECONDS
    while [ $((SECONDS - start_time)) -lt $MAX_WAIT ]; do
        local result
        result=$(curl -sf -X POST http://localhost:1231/getTaskResult \
            -H "Content-Type: application/json" \
            -d "{\"clientKey\": \"local\", \"taskId\": \"$task_id\"}" 2>/dev/null || echo '{"status":"error"}')

        local status
        status=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status","unknown"))' 2>/dev/null || echo "unknown")

        if [ "$status" = "ready" ]; then
            local token
            token=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("solution",{}).get("gRecaptchaResponse",""))' 2>/dev/null || echo "")
            if [ "${#token}" -gt 20 ]; then
                pass "Token obtained (len=${#token})"
                info "Token preview: ${token:0:60}..."
                return 0
            else
                fail "Empty token in ready response"
                return 1
            fi
        elif [ "$status" = "failed" ]; then
            local err
            err=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("errorDescription","unknown"))' 2>/dev/null || echo "unknown")
            fail "Task failed: $err"
            info "The audio challenge may have triggered bot detection."
            info "Check bridge logs: docker logs --tail 50 captcha-bridge"
            return 1
        fi

        # Progress indicator every 30 seconds
        if [ $(( (SECONDS - start_time) % 30 )) -eq 0 ] && [ $((SECONDS - start_time)) -gt 0 ]; then
            local elapsed=$((SECONDS - start_time))
            info "Still processing... (${elapsed}s elapsed)"
        fi
        echo -n "."
        sleep 3
    done

    fail "Timeout waiting for result"
    info "reCAPTCHA v2 audio challenges may trigger bot detection."
    info "Check: docker logs -f captcha-bridge"
    return 1
}

# ── Main ──
main() {
    echo ""
    echo "$(printf '=%.0s' {1..70})"
    echo "  CAPTCHA SOLVING STACK - COMPREHENSIVE TEST SUITE"
    echo "  Started: $(date)"
    echo "$(printf '=%.0s' {1..70})"

    # Ensure we have required tools
    if ! command -v curl >/dev/null 2>&1; then
        echo "ERROR: curl is required"
        exit 1
    fi
    if ! command -v nc >/dev/null 2>&1; then
        echo "WARNING: nc (netcat) not found, port checks may be limited"
    fi

    if [ "$E2E_ONLY" = false ]; then
        test_containers
        test_ports
        test_vision_server
        test_shim
        test_bridge
        test_brave_cdp
        test_whisper
    fi

    if [ "$QUICK_MODE" = false ] && [ "$E2E_ONLY" = false ]; then
        section "E2E TESTS"
        info "The following tests interact with real CAPTCHA demo sites."
        info "They require all services to be running, including Brave browser."
        read -p "Run E2E tests against live CAPTCHA demo sites? [y/N]: " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            test_e2e_hcaptcha
            test_e2e_recaptcha
        else
            warn "E2E tests skipped"
        fi
    elif [ "$E2E_ONLY" = true ]; then
        test_e2e_hcaptcha
        test_e2e_recaptcha
    fi

    # Summary
    section "SUMMARY"
    echo -e "  Total: $((PASS_COUNT + FAIL_COUNT)) | ${GREEN}Pass: $PASS_COUNT${RESET} | ${RED}Fail: $FAIL_COUNT${RESET}"

    if [ $FAIL_COUNT -gt 0 ]; then
        echo ""
        warn "Some tests failed. Common fixes:"
        echo ""
        echo "  1. Start all services:"
        echo "     docker compose up -d"
        echo ""
        echo "  2. Start Brave with CDP:"
        echo "     ./start-brave.sh"
        echo "     # or: systemctl --user start brave-cdp"
        echo ""
        echo "  3. Check vision server logs:"
        echo "     docker logs -f llamacpp-vision"
        echo ""
        echo "  4. Rebuild if needed:"
        echo "     docker compose build --no-cache [service]"
        echo ""
        echo "  5. Run diagnostics:"
        echo "     ./scripts/diagnose.sh"
        echo ""
        exit 1
    else
        echo ""
        pass "All tests passed!"
        exit 0
    fi
}

main "$@" 2>&1 | tee "$REPORT_FILE"
echo ""
echo "  Report saved to: $REPORT_FILE"
