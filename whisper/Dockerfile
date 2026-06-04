FROM debian:bookworm-slim

WORKDIR /app

# Install curl to download the whisperfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download whisperfile (tiny.en = fast, good for short CAPTCHA audio)
# Available models: tiny.en, base.en, small.en
ARG WHISPER_MODEL=tiny.en
RUN curl -L -o whisperfile \
    "https://huggingface.co/Mozilla/whisperfile/resolve/main/whisper-${WHISPER_MODEL}.llamafile" \
    && chmod +x whisperfile

EXPOSE 1233

# Run whisperfile HTTP server
# --host 0.0.0.0: listen on all interfaces
# --port 1233: exposed port
# -l en: English language
# --gpu disable: CPU only (remove for GPU)
CMD ["./whisperfile", "--host", "0.0.0.0", "--port", "1233", "-l", "en", "--gpu", "disable"]
