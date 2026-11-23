from tgmediakit.logsafe import (formatar_excecao_curta, mascarar_email,
                                mascarar_telefone, ocultar_token_em_url)


def test_token_na_url_some():
    assert ocultar_token_em_url("/stream/1?token=abc.def&x=1") == "/stream/1?token=<oculto>&x=1"
    assert ocultar_token_em_url("/a?x=1&access_token=zzz") == "/a?x=1&access_token=<oculto>"


def test_mascaras():
    assert mascarar_email("maria@exemplo.com") == "m***@exemplo.com"
    assert mascarar_email("") == "<vazio>"
    assert mascarar_telefone("+55 11 99999-1234") == "***1234"


def test_excecao_com_html_nao_vaza_a_pagina():
    msg = formatar_excecao_curta(RuntimeError("<html>" + "x" * 1000))
    assert "<html" not in msg and "HTML" in msg


def test_log_de_acesso_real_do_aiohttp_nao_grava_o_token():
    """05/11/2026: AccessLoggerSemToken nao tinha teste. Sobe um servidor aiohttp de verdade com a classe,
    faz requisicoes com token na URL e no Referer e confere a linha que o aiohttp grava no log."""
    import asyncio
    import logging

    import aiohttp
    from aiohttp import web

    from tgmediakit.logsafe import AccessLoggerSemToken

    linhas = []

    class Coletor(logging.Handler):
        def emit(self, record):
            linhas.append(record.getMessage())

    logger = logging.getLogger("teste.acesso")
    logger.setLevel(logging.INFO)
    logger.addHandler(Coletor())

    async def ok(_request):
        return web.Response(text="ok")

    async def principal():
        app = web.Application()
        app.router.add_get("/stream/{id}", ok)
        # mesmo caminho de um servidor real (o TestServer do aiohttp nao repassa as opcoes de log de acesso)
        runner = web.AppRunner(app, access_log=logger, access_log_class=AccessLoggerSemToken,
                               access_log_format='%r %s "%{Referer}i"')
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        porta = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as sessao:
                async with sessao.get(f"http://127.0.0.1:{porta}/stream/7?token=SEGREDO123456789&x=1",
                                      headers={"Referer": "https://app/?jwt=OUTROSEGREDO98765"}) as r:
                    assert r.status == 200
                    await r.read()
            for _ in range(50):                  # o aiohttp grava a linha de acesso DEPOIS de responder
                if linhas:
                    break
                await asyncio.sleep(0.02)
        finally:
            await runner.cleanup()

    asyncio.run(principal())
    texto = "\n".join(linhas)
    assert "/stream/7" in texto, texto                                # a linha de acesso foi gravada
    assert "SEGREDO123456789" not in texto and "OUTROSEGREDO98765" not in texto, texto
    assert "token=<oculto>" in texto and "jwt=<oculto>" in texto, texto
