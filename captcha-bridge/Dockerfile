FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system deps for Playwright CDP client (browser runs externally)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone OhMyCaptcha source
RUN git clone --depth 1 https://github.com/shenhao-stu/ohmycaptcha.git /app/omc_src \
    && rm -rf /app/omc_src/.git

WORKDIR /app/omc_src

# Install OhMyCaptcha dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (needed for CDP client library)
RUN playwright install chromium

# Copy and apply CDP patches
COPY patches/ /app/patches/
RUN python /app/patches/apply_cdp_patches.py

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
