"""pool — several Telegram (Telethon) accounts serving downloads.

Each new request goes to the LEAST busy account, and an account hit by a
FloodWait leaves the queue until Telegram's deadline passes.

Rules
  * The main session is always first; with no extras it behaves like one account.
  * Extras: env `GW_SESSOES_EXTRAS` = session file names inside the sessions
    folder, comma-separated. Missing files are ignored with a warning.
  * A message is fetched and downloaded by the SAME account (file_reference is
    per account): whoever asks for a client keeps it until the end.
  * Never the same session in two processes: each slot copies the file to its
    own name in the temp dir.

Pure logic only (choice, load, penalty); opening/connecting is up to you.
"""
from __future__ import annotations
import logging

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PRINCIPAL = "gw_stream_auth"
CASTIGO_FALHA_S = 60.0          # conta que não abriu/não está autorizada: espera 1 min


@dataclass
class Slot:
    indice: int
    arquivo: Path                # sessão autorizada (fonte da cópia)
    nome_tmp: str                # nome da cópia no %TEMP%
    cliente: object = None
    em_uso: int = 0
    servidos: int = 0
    fora_ate: float = 0.0        # FloodWait / falha: fora da fila até este instante
    motivo: str = ""

    def disponivel(self, agora: float) -> bool:
        return agora >= self.fora_ate


def sessoes_configuradas(pasta: Path, extras: str | None = None, avisar=None) -> list[Slot]:
    """Principal + extras que existem no disco. Duplicadas e a própria principal são ignoradas."""
    extras = os.environ.get("GW_SESSOES_EXTRAS", "") if extras is None else extras
    slots = [Slot(0, pasta / f"{PRINCIPAL}.session", "gw_stream")]
    vistos = {PRINCIPAL}
    for bruto in extras.split(","):
        nome = bruto.strip().removesuffix(".session")
        if not nome or nome in vistos or "/" in nome or "\\" in nome or ".." in nome:
            continue
        vistos.add(nome)
        arq = pasta / f"{nome}.session"
        if not arq.exists():
            if avisar:
                avisar(f"sessão extra {nome} não existe em {pasta} — ignorada")
            continue
        slots.append(Slot(len(slots), arq, f"gw_stream_{len(slots) + 1}"))
    return slots


class Pool:
    def __init__(self, slots: list[Slot], relogio=time.monotonic):
        if not slots:
            raise ValueError("pool sem sessões")
        self.slots = slots
        self.relogio = relogio

    @property
    def multiplo(self) -> bool:
        return len(self.slots) > 1

    def escolher(self) -> Slot:
        """Conta disponível menos ocupada (empate: a que serviu menos; depois a principal).
        Se todas estiverem castigadas, a que volta primeiro — melhor tentar que recusar."""
        agora = self.relogio()
        livres = [s for s in self.slots if s.disponivel(agora)]
        if not livres:
            return min(self.slots, key=lambda s: s.fora_ate)
        return min(livres, key=lambda s: (s.em_uso, s.servidos, s.indice))

    def do_cliente(self, cliente) -> Slot | None:
        return next((s for s in self.slots if s.cliente is not None and s.cliente is cliente), None)

    @contextmanager
    def ocupar(self, cliente):
        """Conta um play em andamento na conta deste cliente (para a escolha dos próximos)."""
        slot = self.do_cliente(cliente)
        if slot is not None:
            slot.em_uso += 1
            slot.servidos += 1
        try:
            yield slot
        finally:
            if slot is not None:
                slot.em_uso = max(0, slot.em_uso - 1)

    def castigar(self, slot: Slot | None, segundos: float, motivo: str) -> None:
        if slot is None:
            return
        slot.fora_ate = max(slot.fora_ate, self.relogio() + max(0.0, float(segundos)))
        slot.motivo = motivo

    def resumo(self) -> list[dict]:
        agora = self.relogio()
        return [{"conta": s.indice + 1, "sessao": s.arquivo.stem, "em_uso": s.em_uso,
                 "servidos": s.servidos, "conectada": bool(s.cliente is not None and _conectado(s.cliente)),
                 "fora_por_s": max(0, round(s.fora_ate - agora)), "motivo": s.motivo if s.fora_ate > agora else ""}
                for s in self.slots]


def _conectado(cliente) -> bool:
    try:
        return bool(cliente.is_connected())
    except (AttributeError, RuntimeError, OSError) as _exc:
        logging.getLogger(__name__).debug("exceção ignorada: %r", _exc)
        return False
