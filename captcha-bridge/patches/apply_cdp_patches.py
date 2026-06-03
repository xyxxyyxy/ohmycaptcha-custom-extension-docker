"""
Patch OhMyCaptcha to connect to Brave via Chrome DevTools Protocol (CDP)
instead of launching its own browser.
"""
import os, re, glob

OMC_DIR = "/app/omc_src"
CDP_URL = os.getenv("CDP_URL", "http://host.docker.internal:9222")
SHIM_URL = os.getenv("SHIM_URL", "http://captcha-solver:8000")

def patch_file(filepath, replacements):
    if not os.path.exists(filepath):
        print(f"SKIP: {filepath} not found")
        return False
    with open(filepath, "r") as f:
        content = f.read()

    original = content
    for old, new in replacements:
        content = content.replace(old, new)

    if content == original:
        print(f"NO CHANGE: {filepath}")
        return False

    with open(filepath, "w") as f:
        f.write(content)
    print(f"PATCHED: {filepath}")
    return True

# Find all Python files that use playwright
py_files = glob.glob(f"{OMC_DIR}/**/*.py", recursive=True)
browser_files = []
for fp in py_files:
    with open(fp, "r") as f:
        content = f.read()
    if "chromium.launch" in content or "async_playwright" in content or "playwright" in content:
        browser_files.append(fp)

print(f"Found {len(browser_files)} files with browser code:")
for bf in browser_files:
    print(f"  {bf}")

# Patch each file: replace launch with connect_over_cdp
for bf in browser_files:
    with open(bf, "r") as f:
        content = f.read()

    # Replace playwright.chromium.launch(...) with connect_over_cdp
    content = re.sub(
        r'await\s+playwright\.chromium\.launch\s*\([^)]*\)',
        f'await playwright.chromium.connect_over_cdp("{CDP_URL}")',
        content
    )

    # Also catch patterns without await
    content = re.sub(
        r'playwright\.chromium\.launch\s*\([^)]*\)',
        f'playwright.chromium.connect_over_cdp("{CDP_URL}")',
        content
    )

    # Remove headless args since CDP doesn't need them
    content = re.sub(
        r'headless\s*=\s*\w+\s*,?\s*',
        '',
        content
    )

    with open(bf, "w") as f:
        f.write(content)
    print(f"PATCHED: {bf}")

# Patch config files if BROWSER_HEADLESS is used
config_files = glob.glob(f"{OMC_DIR}/**/config*.py", recursive=True)
for cf in config_files:
    patch_file(cf, [
        ('BROWSER_HEADLESS = True', 'BROWSER_HEADLESS = False'),
        ('"headless": True', '"headless": False'),
    ])

print("\nCDP patches applied successfully.")
print(f"CDP endpoint: {CDP_URL}")
print(f"Shim endpoint: {SHIM_URL}")
