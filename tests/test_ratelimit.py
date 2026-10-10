"""Testes do Bot/ratelimit.py (janela deslizante por IP + extração de IP real)."""

from tgmediakit.ratelimit import RateLimiter, chamada_interna, ip_real


def test_bloqueia_apos_limite():
    rl = RateLimiter(por_minuto=5)
    assert all(rl.permitir("1.2.3.4") for _ in range(5))
    assert rl.permitir("1.2.3.4") is False


def test_baldes_por_ip_independentes():
    rl = RateLimiter(por_minuto=2)
    assert rl.permitir("1.1.1.1")
    assert rl.permitir("1.1.1.1")
    assert rl.permitir("1.1.1.1") is False
    assert rl.permitir("2.2.2.2")  # outro IP não é afetado


# ⚠️ As margens abaixo são folgadas de PROPÓSITO (28/07/2026). Antes a janela
# era 0.05s com sleep de 0.06s — 10ms de folga, menos que a granularidade do
# `time.sleep` no Windows (~15ms). O teste falhava ~1 vez a cada 3 execuções,
# sem nada de errado no código. Teste que pisca desse jeito treina a gente a
# ignorar suíte vermelha, que é justamente o que o pytest.ini deste projeto
# alerta. Folga de 3x resolve sem deixar a suíte lenta.
def test_janela_desliza():
    rl = RateLimiter(por_minuto=2, janela_s=0.05)
    assert rl.permitir("ip")
    assert rl.permitir("ip")
    assert rl.permitir("ip") is False
    import time
    time.sleep(0.15)  # janela expira (3x a janela, folga p/ o scheduler)
    assert rl.permitir("ip")


def test_gc_remove_baldes_vazios():
    rl = RateLimiter(por_minuto=2, janela_s=0.01)
    rl.permitir("morto")
    import time
    time.sleep(0.10)
    rl._gc(time.monotonic() - 0.01)
    assert "morto" not in rl._hits


# ── IP real atrás da Cloudflare (auditoria de segurança de 13/09/2026) ──────
# Este teste afirmava que valia o 1º do X-Forwarded-For — exatamente o valor
# que o CLIENTE escreve: a Cloudflare preserva o XFF recebido e só anexa o IP
# verdadeiro no fim. Trocar o cabeçalho a cada requisição anulava o rate limit.
def test_ip_real_confia_no_cabecalho_da_cloudflare():
    assert ip_real({"CF-Connecting-IP": "198.51.100.7",
                    "X-Forwarded-For": "1.2.3.4, 198.51.100.7"}, "127.0.0.1") == "198.51.100.7"


def test_ip_real_ignora_o_xff_forjado_pelo_cliente():
    # cliente manda "1.2.3.4"; o proxy anexa o IP de verdade no fim
    assert ip_real({"X-Forwarded-For": "1.2.3.4, 203.0.113.9"}, "127.0.0.1") == "203.0.113.9"
    assert ip_real({"X-Forwarded-For": "127.0.0.1, 203.0.113.9"}, "127.0.0.1") == "203.0.113.9"


def test_ip_real_sem_cabecalho_usa_o_socket():
    assert ip_real({}, "127.0.0.1") == "127.0.0.1"
    assert ip_real({}, None) == "?"


def test_chamada_interna_so_pelo_socket_e_sem_proxy():
    assert chamada_interna({}, "127.0.0.1")
    assert chamada_interna({}, "::1")
    # passou pelo túnel: o socket é 127.0.0.1, mas há cabeçalho de proxy
    assert not chamada_interna({"CF-Connecting-IP": "198.51.100.7"}, "127.0.0.1")
    # o ataque antigo: dizer "sou 127.0.0.1" no cabeçalho não vale nada
    assert not chamada_interna({"X-Forwarded-For": "127.0.0.1"}, "127.0.0.1")
    assert not chamada_interna({}, "203.0.113.9")


def test_middleware_aplica_o_limite_mesmo_com_xff_forjado():
    import asyncio
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    from tgmediakit.ratelimit import aiohttp_middleware

    mw = aiohttp_middleware(RateLimiter(por_minuto=2))

    async def handler(request):
        return web.Response(text="ok")

    async def go():
        codigos = []
        for i in range(4):
            req = make_mocked_request("GET", "/api", headers={
                "CF-Connecting-IP": "198.51.100.7",
                "X-Forwarded-For": f"10.0.0.{i}, 127.0.0.1",   # cliente troca a cada vez
            })
            codigos.append((await mw(req, handler)).status)
        return codigos

    assert asyncio.run(go()) == [200, 200, 429, 429]
