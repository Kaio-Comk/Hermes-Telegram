"""ratelimit — per-IP sliding-window rate limiter (in memory) + aiohttp middleware.

Built for servers behind a Cloudflare tunnel, where the socket IP is always
127.0.0.1: the real client IP comes from proxy headers (see `ip_real`), and
local calls with no proxy header (health checks, curl) skip the limiter
(see `chamada_interna`).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

_GC_INTERVALO_S = 300  # varre baldes vazios a cada 5 min (senão o dict só cresce)


class RateLimiter:
    """Janela deslizante por chave (IP). Um deque de timestamps por chave;
    memória limitada a `limite` floats por IP ativo + GC periódico."""

    def __init__(self, por_minuto: int = 60, janela_s: float = 60.0):
        self.limite = int(por_minuto)
        self.janela = float(janela_s)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._ultimo_gc = time.monotonic()

    def permitir(self, chave: str) -> bool:
        """True se a requisição cabe na janela; False = responder 429."""
        agora = time.monotonic()
        corte = agora - self.janela
        dq = self._hits[chave]
        while dq and dq[0] <= corte:
            dq.popleft()
        if len(dq) >= self.limite:
            return False
        dq.append(agora)
        if agora - self._ultimo_gc > _GC_INTERVALO_S:
            self._gc(corte)
            self._ultimo_gc = agora
        return True

    def _gc(self, corte: float) -> None:
        for chave in list(self._hits):
            dq = self._hits[chave]
            while dq and dq[0] <= corte:
                dq.popleft()
            if not dq:
                del self._hits[chave]


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_CABECALHOS_DE_PROXY = ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP")


def ip_real(headers, fallback: str | None) -> str:
    """Real client IP behind a proxy/Cloudflare tunnel.

    NEVER trust the first X-Forwarded-For entry: the client controls it and a
    rotating fake value would dodge the limiter. Trust order:
      1. CF-Connecting-IP (written by Cloudflare, overrides the client's);
      2. the LAST X-Forwarded-For entry (appended by the proxy);
      3. the socket address.
    """
    cf = (headers.get("CF-Connecting-IP") or "").strip()
    if cf:
        return cf
    xff = headers.get("X-Forwarded-For") or ""
    ultimo = xff.split(",")[-1].strip() if xff else ""
    return ultimo or fallback or "?"


def chamada_interna(headers, remoto: str | None) -> bool:
    """Requisição feita na própria máquina, sem passar pelo túnel (canário,
    importador publicando no cache, curl local). Decide pelo SOCKET e pela
    AUSÊNCIA de cabeçalho de proxy — nunca por um IP que veio em cabeçalho,
    que o cliente controla."""
    if (remoto or "") not in _LOOPBACK:
        return False
    return not any(headers.get(h) for h in _CABECALHOS_DE_PROXY)


def aiohttp_middleware(limiter: RateLimiter, isentos: tuple[str, ...] = ()):
    """Fábrica de middleware aiohttp. `isentos` = prefixos de path fora do balde."""
    from aiohttp import web  # lazy: quem só usa a classe não precisa de aiohttp

    @web.middleware
    async def _rate_limit(request, handler):
        path = request.path
        if any(path.startswith(p) for p in isentos):
            return await handler(request)
        if chamada_interna(request.headers, request.remote):
            return await handler(request)
        if not limiter.permitir(ip_real(request.headers, request.remote)):
            return web.json_response({"detail": "Too Many Requests"},
                                     status=429, headers={"Retry-After": "30"})
        return await handler(request)

    return _rate_limit
