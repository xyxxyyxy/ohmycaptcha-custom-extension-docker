"""
Patch OhMyCaptcha to connect to Brave via Chrome DevTools Protocol (CDP)
instead of launching its own headless browser.

Run this after cloning OhMyCaptcha but before starting the server.
"""
import os, re, sys

OMC_DIR = "/app/omc_src"

def patch_file(filepath, old, new):
    if not os.path.exists(filepath):
        print(f"SKIP: {filepath} not found")
        return
    with open(filepath, "r") as f:
        content = f.read()
    if old not in content:
        print(f"SKIP: pattern not found in {filepath}")
        return
    content = content.replace(old, new)
    with open(filepath, "w") as f:
        f.write(content)
    print(f"PATCHED: {filepath}")

# Find browser launch code and replace with CDP connect
# This is a generic patch — we look for playwright.chromium.launch patterns
browser_files = []
for root, dirs, files in os.walk(OMC_DIR):
    for f in files:
        if f.endswith(".py"):
            fp = os.path.join(root, f)
            with open(fp, "r") as fh:
                content = fh.read()
            if "chromium.launch" in content or "browser.new_context" in content:
                browser_files.append(fp)

print(f"Found {len(browser_files)} files with browser code:")
for bf in browser_files:
    print(f"  {bf}")

# Patch each file: replace launch with CDP connect
for bf in browser_files:
    with open(bf, "r") as f:
        content = f.read()

    # Replace playwright.chromium.launch(...) with connect_over_cdp
    # This is a broad regex — may need tuning per OhMyCaptcha version
    content = re.sub(
        r'await\s+playwright\.chromium\.launch\s*\([^)]*\)',
        'await playwright.chromium.connect_over_cdp(os.getenv("CDP_URL", "http://host.docker.internal:9222"))',
        content
    )

    # Also catch sync version
    content = re.sub(
        r'playwright\.chromium\.launch\s*\([^)]*\)',
        'playwright.chromium.connect_over_cdp(os.getenv("CDP_URL", "http://host.docker.internal:9222"))',
        content
    )

    with open(bf, "w") as f:
        f.write(content)
    print(f"PATCHED: {bf}")

print("\nCDP patch complete.")
