# tgmediakit

Small, dependency-light helpers extracted from a production Telegram media bot
(Telethon + aiogram + aiohttp). Each module stands alone.

| Module | What it does |
|---|---|
| `tgmediakit.parallel_download` | Download a Telegram document over N concurrent connections, written in order (so the `.part` file can be streamed while it grows). Falls back to `download_media()` on any error and refreshes expired file references. |
| `tgmediakit.pool` | Pool of several Telethon accounts: least-busy choice, FloodWait penalty, safe single-account default. Pure logic; you open the clients. |
| `tgmediakit.ratelimit` | Sliding-window per-IP limiter + aiohttp middleware that reads the real IP behind Cloudflare (never trusts the first `X-Forwarded-For`). |
| `tgmediakit.logsafe` | Hide access tokens in aiohttp access logs; mask e-mails and phones; short, HTML-free exception strings. |

## Install

```bash
pip install git+https://github.com/Kaio-Comk/tgmediakit.git
# ratelimit's middleware and logsafe's access logger need aiohttp:
pip install "aiohttp>=3.9"
```

## Example

```python
from pathlib import Path
from tgmediakit.parallel_download import download_parallel

msg = await client.get_messages(chat_id, ids=message_id)
await download_parallel(client, msg, Path("video.mp4"), connections=4)
```

Parallel downloads can hit Telegram flood limits on `GetFileRequest`; keep
`connections` modest (2-4) and use `tgmediakit.pool` to spread load.

## Tests

```bash
pip install -e ".[dev]" && pytest
```

## Contributing

Issues and pull requests are welcome, including ideas for the next modules
(a Supabase-backed job queue with leases, and an AC3-to-AAC audio repair worker,
are on the list once they are decoupled from the original bot).

## License

MIT
