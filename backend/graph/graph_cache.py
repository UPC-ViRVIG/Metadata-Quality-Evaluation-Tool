import hashlib
import json
import threading
from rdflib import Graph

_cache: dict[str, Graph] = {}
_lock = threading.Lock()


def _make_key(source_config: dict) -> str:
    """
    Return a stable SHA-256 hex digest for a source configuration.
    """
    canonical = json.dumps(source_config, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get(source_config: dict) -> Graph | None:
    """
    Return the cached Graph for the source configuration, or None if not cached.
    """
    key = _make_key(source_config)
    with _lock:
        return _cache.get(key)


def store(source_config: dict, graph: Graph) -> None:
    """
    Store graph in the cache under the corresponding source_config.
    """
    key = _make_key(source_config)
    with _lock:
        if key not in _cache:
            _cache[key] = graph


def get_or_load(source_config: dict, loader_fn) -> Graph:
    """
    Return the cached graph, or produces it and stores the 
    result.

    Parameters
    ----------
    source_config : dict
    loader_fn : callable
        Zero-argument callable that returns an rdflib.Graph.
        Called only on cache miss.
    """
    cached = get(source_config)
    if cached is not None:
        return cached

    graph = loader_fn()
    store(source_config, graph)
    return graph


def invalidate(source_config: dict) -> bool:
    """
    Remove source_config from the cache.

    Returns True if an entry was removed, False if nothing was cached.
    """
    key = _make_key(source_config)
    with _lock:
        if key in _cache:
            del _cache[key]
            return True
        return False


def clear() -> None:
    """Evict all cached graphs."""
    with _lock:
        _cache.clear()