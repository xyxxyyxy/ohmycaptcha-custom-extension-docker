#!/usr/bin/env bash
#
# Download Qwen3VL model + mmproj for the dedicated vision server.
# Uses the Hugging Face CLI (https://hf.co/cli/)
#
# Usage:
#   ./download-vision-model.sh          # Downloads Q4_K_M (recommended for 8GB)
#   ./download-vision-model.sh f16      # Downloads F16 (best quality, ~16GB)
#   ./download-vision-model.sh q8_0     # Downloads Q8_0 (good quality, ~8.5GB)
#
# Target directory: /mnt/hdd/models
# After download: docker compose up -d llamacpp-vision

set -euo pipefail

QUANT="${1:-q4_k_m}"
QUANT_LOWER="$(echo "$QUANT" | tr '[:upper:]' '[:lower:]')"

DEST_DIR="/mnt/hdd/models"
REPO="unsloth/Qwen3-VL-8B-Instruct-GGUF"

# Map quant name to HF file
 case "$QUANT_LOWER" in
   q4_k_m)
     MODEL_FILE="Qwen3-VL-8B-Instruct-Q4_K_M.gguf"
     ;;
   q8_0)
     MODEL_FILE="Qwen3-VL-8B-Instruct-Q8_0.gguf"
     ;;
   f16)
     MODEL_FILE="Qwen3-VL-8B-Instruct-F16.gguf"
     ;;
   *)
     echo "Unknown quant: $QUANT"
     echo "Valid options: q4_k_m, q8_0, f16"
     exit 1
     ;;
 esac

MMPROJ_FILE="mmproj-Qwen3-VL-8B-Instruct-F16.gguf"

echo "=========================================="
echo "  Download Qwen3VL Vision Model"
echo "=========================================="
echo "  Quant:     $QUANT"
echo "  Model:     $MODEL_FILE"
echo "  mmproj:    $MMPROJ_FILE"
echo "  Repo:      $REPO"
echo "  Dest:      $DEST_DIR"
echo ""

# Check/install hf CLI
if ! command -v hf &> /dev/null; then
  echo "hf CLI not found. Installing..."
  echo "  curl -sSL https://hf.co/cli/install | sh"
  curl -sSL https://hf.co/cli/install | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Verify hf works
if ! command -v hf &> /dev/null; then
  echo "ERROR: hf CLI installation failed. Try:"
  echo "  curl -sSL https://hf.co/cli/install | sh"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  exit 1
fi

echo "hf CLI: $(hf --version 2>/dev/null || echo 'version unknown')"
echo ""

# Create dest directory
mkdir -p "$DEST_DIR"

echo "Downloading model file..."
echo "  hf download $REPO $MODEL_FILE --local-dir $DEST_DIR"
hf download "$REPO" "$MODEL_FILE" --local-dir "$DEST_DIR"

echo ""
echo "Downloading mmproj file..."
echo "  hf download $REPO $MMPROJ_FILE --local-dir $DEST_DIR"
hf download "$REPO" "$MMPROJ_FILE" --local-dir "$DEST_DIR"

echo ""
echo "=========================================="
echo "  Download Complete!"
echo "=========================================="
echo ""
echo "Files in $DEST_DIR:"
ls -lh "$DEST_DIR/$MODEL_FILE" "$DEST_DIR/$MMPROJ_FILE" 2>/dev/null || true
echo ""
echo "Symlink to ai-models (optional):"
echo "  ln -sf $DEST_DIR/$MODEL_FILE $DEST_DIR/../ai-models/Qwen3VL-8B-Instruct-${QUANT_UPPER}.gguf"
echo ""
echo "Next steps:"
echo "  1. If you used a non-default quant, update docker-compose.yml:"
echo "       MODEL_PATH=/models/$MODEL_FILE"
echo "  2. Update the quant suffix in docker-compose.yml env vars"
echo "  3. Start the vision server:"
echo "       docker compose up -d llamacpp-vision"
echo ""
