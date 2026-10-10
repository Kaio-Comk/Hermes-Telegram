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
