"""
Tiny in-process pub/sub broker used for Server-Sent Events (real-time updates).
For multi-process deployments, replace publish()/subscribe() with Redis pub/sub.
"""
import json
import queue
import threading
from collections import defaultdict

_lock = threading.Lock()
_subscribers = defaultdict(set)  # session_id -> set[queue.Queue]


def subscribe(session_id):
    q = queue.Queue(maxsize=200)
    with _lock:
        _subscribers[session_id].add(q)
    return q


def unsubscribe(session_id, q):
    with _lock:
        _subscribers[session_id].discard(q)


def publish(session_id, payload):
    """Send an event to every screen watching this session. Never blocks."""
    msg = json.dumps(payload)
    with _lock:
        targets = list(_subscribers[session_id])
    for q in targets:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass  # slow client; it will resync on reconnect
