import asyncio
import json
import os

import dotenv
from redis.asyncio import Redis

dotenv.load_dotenv()

# Initialize Redis connection
redis_client = Redis(
    host=os.environ.get("REDIS_HOST"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    username=os.environ.get("REDIS_USERNAME"),
    password=os.environ.get("REDIS_PASSWORD"),
    decode_responses=True  # return strings instead of bytes
)

async def get_cached_swap_id(swap_id: str):
    """
    Fetch cached swap data by swapId. Returns dict or None.
    """
    cache_key = f"swap:{swap_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    return None


async def cache_swap_data(swap_id: str, data: dict):
    """
    Cache swap data with a short redis lock to prevent race conditions.
    """
    cache_key = f"swap:{swap_id}"
    lock_key = f"{cache_key}:lock"
    cache_expiry_seconds = 15 * 60  # 15 minutes
    lock_timeout = 15  # seconds

    # Acquire lock (SET key value NX EX 15)
    lock_acquired = await redis_client.set(
        lock_key, "locked", ex=lock_timeout, nx=True
    )

    if lock_acquired:
        try:
            await redis_client.set(
                cache_key,
                json.dumps(data),
                ex=cache_expiry_seconds
            )
        finally:
            # Always release the lock
            await redis_client.delete(lock_key)
    else:
        # Wait briefly and retry once
        await asyncio.sleep(1)
        return await cache_swap_data(swap_id, data)
