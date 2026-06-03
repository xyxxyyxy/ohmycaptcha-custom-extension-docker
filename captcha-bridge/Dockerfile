FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system deps for Playwright CDP client
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-patched OhMyCaptcha source (patches applied in repo)
COPY omc_src /app/omc_src

WORKDIR /app/omc_src

# Install OhMyCaptcha dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (needed for CDP client library)
RUN playwright install chromium

EXPOSE 1231

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "1231"]
