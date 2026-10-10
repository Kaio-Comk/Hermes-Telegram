"""parallel_download — download a Telegram document over N concurrent connections.

Telethon's `download_media()` is one sequential chain of requests (~1.5 MB/s in
our tests: a 1 GB file took ~11 min). Here the file is split in 1 MB blocks
fetched by `connections` tasks (stride), while a single writer appends blocks
IN ORDER, so the growing `.part` file can be served while it downloads.

Any error falls back to the classic `download_media()` (speed never justifies a
broken download). `FileReferenceExpiredError` re-fetches the message first.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

BLOCK = 1024 * 1024          # Telegram's request_size ceiling
_MIN_PARALLEL_BLOCKS = 8     # smaller files are not worth it


async def download_parallel(client, msg, dest: Path, progress_cb=None, *,
                            connections: int = 4) -> None:
    total = int(getattr(msg.document, "size", 0) or 0)
    connections = max(1, int(connections))
    if connections == 1 or total < _MIN_PARALLEL_BLOCKS * BLOCK:
        await client.download_media(msg, str(dest), progress_callback=progress_cb)
        return

    pending: dict[int, bytes] = {}
    next_off = 0
    done_bytes = 0
    # Credit PER TRACK (not a shared buffer): with one shared semaphore the
    # fast tracks eat every credit and the track owning the block the writer
    # waits for starves -> deadlock. 2 per track bounds memory (connections x 2 MB).
    credits = [asyncio.Semaphore(2) for _ in range(connections)]

    def _write(f, chunk: bytes) -> None:
        f.write(chunk)
        f.flush()

    async def _track(index: int) -> None:
        offset = index * BLOCK
        while offset < total:
            await credits[index].acquire()
            chunk = b""
            async for part in client.iter_download(
                    msg.document, offset=offset, request_size=BLOCK, limit=1):
                chunk += part
            if not chunk:
                credits[index].release()
                break
            pending[offset] = chunk
            offset += BLOCK * connections

    tasks: list = []
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            tasks = [asyncio.create_task(_track(i)) for i in range(connections)]
            while next_off < total:
                chunk = pending.pop(next_off, None)
                if chunk is None:
                    if all(t.done() for t in tasks):
                        errs = [t.exception() for t in tasks
                                if t.done() and not t.cancelled() and t.exception()]
                        if errs:
                            raise errs[0]
                        break
                    await asyncio.sleep(0.05)
                    continue
                owner = (next_off // BLOCK) % connections
                await asyncio.to_thread(_write, f, chunk)
                next_off += len(chunk)
                done_bytes += len(chunk)
                credits[owner].release()
                if progress_cb:
                    progress_cb(done_bytes, total)
            for task in tasks:
                task.cancel()
            # collect every result: otherwise a dead track's exception is
            # logged as "Task exception was never retrieved"
            await asyncio.gather(*tasks, return_exceptions=True)
        written = dest.stat().st_size
        if written != total:
            raise IOError(f"final size {written} != expected {total}")
    except Exception as e:  # noqa: BLE001 - any failure falls back to the classic path
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.warning("parallel download failed (%s); falling back to download_media", e)
        dest.unlink(missing_ok=True)
        if type(e).__name__ == "FileReferenceExpiredError":
            try:
                fresh = await client.get_messages(msg.chat_id, ids=msg.id)
                if fresh is not None and getattr(fresh, "document", None):
                    msg = fresh
            except (OSError, RuntimeError, ValueError) as exc_ref:
                log.warning("could not refresh the file reference: %s", exc_ref)
        await client.download_media(msg, str(dest), progress_callback=progress_cb)
