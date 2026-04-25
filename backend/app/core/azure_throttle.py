"""Global Azure API rate-limiter.

Limits the total number of concurrent Azure Management API calls
across ALL services to prevent HTTP 429 throttling.
"""

import asyncio

# Azure Cost Management allows ~10 requests/min per subscription.
# Keep concurrency low to avoid 429s.
AZURE_API_SEMAPHORE = asyncio.Semaphore(2)
