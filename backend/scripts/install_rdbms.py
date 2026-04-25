"""Install azure-mgmt-rdbms by downloading and extracting the wheel directly."""

import os
import signal
import sys
import tempfile
import urllib.request
import zipfile

signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ignore SIGINT

SITE_PACKAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
WHEEL_URL = "https://files.pythonhosted.org/packages/ec/c4/7443bbb09a160edcd9a03374e6758e080ff43c748f6070c1b5ee73d2bf80/azure_mgmt_rdbms-10.1.1-py3-none-any.whl"

print(f"Target: {SITE_PACKAGES}")

# Remove old dist-info
old_dist = os.path.join(SITE_PACKAGES, "azure_mgmt_rdbms-10.1.1.dist-info")
if os.path.exists(old_dist):
    import shutil

    shutil.rmtree(old_dist)
    print("Removed old dist-info")

# Download wheel
tmp = os.path.join(tempfile.gettempdir(), "azure_mgmt_rdbms.whl")
print("Downloading wheel...")
try:
    proxy_handler = urllib.request.ProxyHandler(
        {
            "http": os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", "")),
            "https": os.environ.get("HTTPS_PROXY", os.environ.get("https_proxy", "")),
        }
    )
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(WHEEL_URL, tmp)
    print(f"Downloaded to {tmp}")
except Exception as e:
    print(f"Download failed: {e}")
    # Try without proxy
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(WHEEL_URL, tmp)
        print(f"Downloaded (no proxy) to {tmp}")
    except Exception as e2:
        print(f"Download failed (no proxy): {e2}")
        sys.exit(1)

# Extract wheel into site-packages
print("Extracting wheel...")
with zipfile.ZipFile(tmp, "r") as whl:
    whl.extractall(SITE_PACKAGES)

print("Verifying...")
init_path = os.path.join(SITE_PACKAGES, "azure", "mgmt", "rdbms", "__init__.py")
pg_path = os.path.join(SITE_PACKAGES, "azure", "mgmt", "rdbms", "postgresql_flexibleservers")
print(f"  __init__.py exists: {os.path.exists(init_path)}")
print(f"  postgresql_flexibleservers exists: {os.path.exists(pg_path)}")

os.remove(tmp)
print("DONE - restart backend for changes to take effect")
