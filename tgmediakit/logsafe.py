"""logsafe — keep access tokens and personal data out of logs.

Access tokens often travel in the query string (native apps build URLs that
way) and the aiohttp access log records the whole URL. `AccessLoggerSemToken`
replaces the token with `<oculto>`; `mascarar_email` / `mascarar_telefone`
keep just enough to be useful for support.
"""
from __future__ import annotations

import re

from aiohttp.web_log import AccessLogger

_TOKEN_NA_URL = re.compile(r"(?i)([?&](?:token|access_token|jwt|tk)=)[^&\s\"']+")


def ocultar_token_em_url(texto):
    if not isinstance(texto, str) or not texto:
        return texto
    return _TOKEN_NA_URL.sub(r"\1<oculto>", texto)


def mascarar_email(email) -> str:
    s = str(email or "").strip()
    if not s:
        return "<vazio>"
    local, arroba, dominio = s.partition("@")
    if not arroba:
        return s[:1] + "***"
    return f"{local[:1]}***@{dominio}"


def mascarar_telefone(telefone) -> str:
    digitos = re.sub(r"\D", "", str(telefone or ""))
    return f"***{digitos[-4:]}" if len(digitos) >= 4 else "***"


class AccessLoggerSemToken(AccessLogger):
    """Log de acesso do aiohttp com o token trocado por `<oculto>` na linha da
    requisição e no Referer. O `compile_format` do aiohttp amarra os
    formatadores à classe base, então o saneamento fica no `_format_line`."""

    def _format_line(self, request, response, time):
        return [(chave, ocultar_token_em_url(valor))
                for chave, valor in super()._format_line(request, response, time)]


def formatar_excecao_curta(exc, max_len: int = 250) -> str:
    """Formata uma exceção para log sem vazar HTML gigante (ex.: 520 Cloudflare) nem estourar linhas."""
    if exc is None:
        return ""
    # Se for APIError ou dict com dados de erro PostgREST/Supabase
    if hasattr(exc, "args") and exc.args and isinstance(exc.args[0], dict):
        d = exc.args[0]
        code = d.get("code")
        msg = d.get("message")
        if code or msg:
            hint = d.get("hint")
            extra = f" (hint={hint})" if hint and not any(tag in str(hint).lower() for tag in ("<html", "<!doctype")) else ""
            return f"APIError: {msg or 'erro'} [code={code}]{extra}"
    s = str(exc)
    # Se contiver HTML bruto (páginas de erro de proxy como Cloudflare 502/520)
    if any(tag in s.lower() for tag in ("<html", "<!doctype", "cf-error", "cloudflare")):
        return f"{type(exc).__name__}: resposta HTML de erro do gateway (tam={len(s)} bytes)"
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s

