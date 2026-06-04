#!/bin/bash
# Patch hip.h for ROCm 6.2 (lacks __hip_fp8_e4m3, added in 6.3)
HIP_FILE="/build/llama.cpp/ggml/src/ggml-cuda/vendors/hip.h"

if grep -q "typedef __hip_fp8_e4m3 __nv_fp8_e4m3;" "$HIP_FILE"; then
    # Insert fallback typedef before the line
    sed -i '/typedef __hip_fp8_e4m3 __nv_fp8_e4m3;/i\
#ifndef __hip_fp8_e4m3\
  typedef unsigned char __hip_fp8_e4m3;  // fallback for ROCm < 6.3\
#endif\
' "$HIP_FILE"
    echo "Patched $HIP_FILE for ROCm 6.2"
else
    echo "No patch needed (already patched or different hip.h)"
fi
