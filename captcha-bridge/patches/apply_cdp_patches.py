"""
Patch OhMyCaptcha to connect to Brave via Chrome DevTools Protocol (CDP)
instead of launching its own browser.

This patches all Playwright browser.launch() calls to use connect_over_cdp()
pointing at the external Brave/Chromium instance.
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


# ── Browser launch → CDP connect ──
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

for bf in browser_files:
    with open(bf, "r") as f:
        content = f.read()

    original = content

    # Replace playwright.chromium.launch(...) with connect_over_cdp
    content = re.sub(
        r'await\s+playwright\.chromium\.launch\s*\([^)]*\)',
        f'await playwright.chromium.connect_over_cdp("{CDP_URL}")',
        content,
    )

    # Also catch patterns without await
    content = re.sub(
        r'playwright\.chromium\.launch\s*\([^)]*\)',
        f'playwright.chromium.connect_over_cdp("{CDP_URL}")',
        content,
    )

    # Remove headless args since CDP doesn't need them
    content = re.sub(
        r'headless\s*=\s*\w+\s*,?\s*\n?',
        '\n',
        content,
    )

    # Remove --no-sandbox args (not needed with CDP)
    content = re.sub(
        r'"--no-sandbox",?\s*\n?',
        '\n',
        content,
    )

    # Remove --disable-dev-shm-usage (not needed with CDP)
    content = re.sub(
        r'"--disable-dev-shm-usage",?\s*\n?',
        '\n',
        content,
    )

    # Remove --disable-gpu (not needed with CDP)
    content = re.sub(
        r'"--disable-gpu",?\s*\n?',
        '\n',
        content,
    )

    # Remove --disable-setuid-sandbox (not needed with CDP)
    content = re.sub(
        r'"--disable-setuid-sandbox",?\s*\n?',
        '\n',
        content,
    )

    if content != original:
        with open(bf, "w") as f:
            f.write(content)
        print(f"PATCHED: {bf}")
    else:
        print(f"NO CHANGE: {bf}")


# ── Config: force headless=false ──
config_files = glob.glob(f"{OMC_DIR}/**/config*.py", recursive=True)
for cf in config_files:
    patch_file(cf, [
        ("BROWSER_HEADLESS = True", "BROWSER_HEADLESS = False"),
        ('"headless": True', '"headless": False"'),
    ])

# ── Also patch any solver that creates its own browser context ──
# Some solvers may use Browser.new_context() with specific args
for bf in browser_files:
    with open(bf, "r") as f:
        content = f.read()

    # Remove viewport args that might conflict with real browser
    content = re.sub(
        r'viewport\s*=\s*\{[^}]*\}',
        '',
        content,
    )

    with open(bf, "w") as f:
        f.write(content)

print("\nCDP patches applied successfully.")
print(f"CDP endpoint: {CDP_URL}")
print(f"Shim endpoint: {SHIM_URL}")
