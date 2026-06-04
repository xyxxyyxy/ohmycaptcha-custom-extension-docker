#!/usr/bin/env bash
#
# Test the fallback handler (self-hosted → OpenRouter).
# Requires OPENROUTER_API_KEY to be set.
#
# Usage:
#   export OPENROUTER_API_KEY=sk-or-v1-...
#   ./scripts/test-fallback.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SHIM_URL="http://localhost:1232"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
pass() { echo -e "${GREEN}  PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "${RED}  FAIL${NC} $1"; ((FAIL++)); }
warn() { echo -e "${YELLOW}  WARN${NC} $1"; ((WARN++)); }
info() { echo -e "${BLUE}  INFO${NC} $1"; }

echo ""
echo "======================================================================"
echo "  FALLBACK HANDLER TEST"
echo "  Tests: self-hosted → OpenRouter failover"
echo "======================================================================"

# ── 1. Check stats ──
echo ""
echo "--- 1. Shim Stats ---"
if curl -sf "$SHIM_URL/stats" -o /tmp/fallback-stats.json 2>/dev/null; then
    cat /tmp/fallback-stats.json | python3 -m json.tool 2>/dev/null || cat /tmp/fallback-stats.json
    pass "/stats responds"
else
    fail "/stats not available (is captcha-solver running?)"
    exit 1
fi

# ── 2. Test text chat (no fallback needed usually) ──
echo ""
echo "--- 2. Text Chat ---"
RESPONSE=$(curl -sf "$SHIM_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{"model":"Qwen3VL-8B-Instruct-Q4_K_M","messages":[{"role":"user","content":"Say 'test' and nothing else."}],"max_tokens":10}' \
    2>/dev/null || echo "")

if [ -n "$RESPONSE" ]; then
    ANSWER=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null || echo "")
    if [ -n "$ANSWER" ]; then
        pass "Text chat: '$ANSWER'"
    else
        fail "Text chat empty"
    fi
else
    fail "Text chat no response"
fi

# ── 3. Test vision chat (may trigger fallback) ──
echo ""
echo "--- 3. Vision Chat ---"
if command -v python3 &>/dev/null; then
    TEST_JSON=$(python3 -c '
import base64, io, json
from PIL import Image
img = Image.new("RGB", (50, 50), "green")
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

    START_TIME=$(date +%s.%N)
    RESPONSE=$(curl -sf "$SHIM_URL/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d "$TEST_JSON" \
        -w "\n%{http_code}" \
        2>/dev/null || echo "")
    END_TIME=$(date +%s.%N)
    ELAPSED=$(python3 -c "print(f'{$END_TIME - $START_TIME:.1f}')")

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        ANSWER=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'])" 2>/dev/null || echo "")
        if [ -n "$ANSWER" ]; then
            pass "Vision chat: '$ANSWER' (${ELAPSED}s)"
        else
            fail "Vision chat empty (${ELAPSED}s)"
        fi
    else
        fail "Vision chat HTTP $HTTP_CODE (${ELAPSED}s)"
        info "Response: $(echo "$BODY" | head -c 200)"
    fi
else
    warn "python3 not available, skipping vision test"
fi

# ── 4. Check fallback stats ──
echo ""
echo "--- 4. Fallback Stats ---"
if curl -sf "$SHIM_URL/stats" -o /tmp/fallback-stats2.json 2>/dev/null; then
    SELF=$(python3 -c "import json; print(json.load(open('/tmp/fallback-stats2.json')).get('self_hosted_success', '?'))")
    FB=$(python3 -c "import json; print(json.load(open('/tmp/fallback-stats2.json')).get('fallback_count', '?'))")
    OR_CONF=$(python3 -c "import json; print(json.load(open('/tmp/fallback-stats2.json')).get('openrouter_configured', '?'))")

    info "Self-hosted successes: $SELF"
    info "Fallback count: $FB"
    info "OpenRouter configured: $OR_CONF"

    if [ "$FB" != "0" ] && [ "$FB" != "?" ]; then
        warn "Fallback was used $FB times (self-hosted may be failing)"
    elif [ "$SELF" != "0" ] && [ "$SELF" != "?" ]; then
        pass "Self-hosted working (no fallback needed)"
    fi
fi

# ── Summary ──
echo ""
echo "======================================================================"
echo "  RESULTS: PASS=$PASS FAIL=$FAIL"
echo "======================================================================"
