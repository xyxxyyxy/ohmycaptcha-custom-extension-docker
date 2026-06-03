FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system deps for Playwright/Chromium (needed for CDP client)
RUN apt-get update && apt-get install -y --no-install-recommends     curl wget gnupg ca-certificates procps git     libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0     libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1     libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2     libatspi2.0-0 libwayland-client0 libwayland-egl1 libx11-xcb1     libxcursor1 libxi6 libxtst6 libappindicator3-1 libdbus-glib-1-2     && rm -rf /var/lib/apt/lists/*

# Clone OhMyCaptcha source
RUN git clone --depth 1 https://github.com/shenhao-stu/ohmycaptcha.git /app/omc_src     && rm -rf /app/omc_src/.git

# Copy requirements and install ALL deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Install Playwright browsers (needed for CDP client)
RUN playwright install chromium

# Copy patches
COPY patches/ /app/patches/

# Apply CDP patches
RUN python /app/patches/apply_cdp_patches.py

EXPOSE 8000

# OhMyCaptcha's main.py will be patched to use CDP
CMD cd /app/omc_src && uvicorn main:app --host 0.0.0.0 --port 8000
