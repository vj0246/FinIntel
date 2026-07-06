"""
graph_stream.py
---------------
Bridge between LangGraph's SYNC stream and our async SSE generators.

Why sync: dynamic `interrupt()` needs the runnable-config contextvar inside
the node. LangGraph only propagates that context to async tasks on Python
3.11+; the sync execution path sets it in-thread and works everywhere
(local py3.10 and Render py3.11 alike). So HITL graphs run `graph.stream`
in a worker thread and updates are forwarded to the event loop via a queue —
the SSE stream stays incremental.
"""

import asyncio
import threading


async def astream_updates(graph, inp, config, timeout: float = 300):
    """Async iterator over `graph.stream(inp, config, stream_mode='updates')`.

    Yields each update dict as it lands. Raises the node's exception if the
    graph fails; raises TimeoutError if nothing completes for `timeout` s.
    """
    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def run():
        try:
            for update in graph.stream(inp, config=config, stream_mode="updates"):
                loop.call_soon_threadsafe(q.put_nowait, ("update", update))
        except Exception as e:            # surfaced to the async consumer
            loop.call_soon_threadsafe(q.put_nowait, ("error", e))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, ("done", None))

    threading.Thread(target=run, daemon=True).start()

    while True:
        kind, payload = await asyncio.wait_for(q.get(), timeout=timeout)
        if kind == "done":
            return
        if kind == "error":
            raise payload
        yield payload


def interrupt_payload(update: dict):
    """The payload of a pending interrupt in an updates-stream event, or None."""
    ints = update.get("__interrupt__")
    if ints:
        return ints[0].value
    return None


async def has_pending_interrupt(graph, config) -> bool:
    """True if this thread is paused at an interrupt and can be resumed."""
    try:
        state = await asyncio.to_thread(graph.get_state, config)
        return bool(state.next)
    except Exception:
        return False
