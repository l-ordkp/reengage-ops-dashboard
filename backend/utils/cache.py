"""TTL cache decorator using cachetools."""
from __future__ import annotations

import functools

from cachetools import TTLCache


def cached(ttl: int = 300, maxsize: int = 8):
    """
    Decorator: cache the function's return value for `ttl` seconds.
    Cache key = (func_name, *args, *kwargs.items()).
    The wrapped function exposes `.clear()` to invalidate the cache.
    """
    def decorator(func):
        cache = TTLCache(maxsize=maxsize, ttl=ttl)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (func.__name__,) + args + tuple(sorted(kwargs.items()))
            if key in cache:
                return cache[key]
            result = func(*args, **kwargs)
            cache[key] = result
            return result

        wrapper.cache = cache
        wrapper.clear = cache.clear  # type: ignore[attr-defined]
        return wrapper

    return decorator
