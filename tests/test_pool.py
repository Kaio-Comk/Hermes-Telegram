"""Session pool: least-busy account choice, FloodWait penalty, single-account default."""
from pathlib import Path

import pytest

from tgmediakit import pool as ps


class Relogio:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Cliente:
    def __init__(self, nome, autorizado=True):
        self.nome, self._autorizado, self.conectado = nome, autorizado, True

    def is_connected(self):
        return self.conectado

    async def is_user_authorized(self):
        return self._autorizado

    async def disconnect(self):
        self.conectado = False


def _pasta(tmp_path, *extras):
    for n in ("gw_stream_auth", *extras):
        (tmp_path / f"{n}.session").write_bytes(b"x")
    return tmp_path


# ── configuração ─────────────────────────────────────────────────────────────
def test_sem_extras_so_a_principal(tmp_path):
    slots = ps.sessoes_configuradas(_pasta(tmp_path), extras="")
    assert [s.arquivo.name for s in slots] == ["gw_stream_auth.session"] and slots[0].nome_tmp == "gw_stream"
    assert not ps.Pool(slots).multiplo


def test_extras_existentes_entram_na_ordem_e_o_resto_e_ignorado(tmp_path):
    avisos = []
    slots = ps.sessoes_configuradas(
        _pasta(tmp_path, "gw_stream_auth_2", "gw_stream_auth_3"),
        extras=" gw_stream_auth_2.session, falta, gw_stream_auth_2, gw_stream_auth, ../fora, gw_stream_auth_3 ",
        avisar=avisos.append)
    assert [s.arquivo.stem for s in slots] == ["gw_stream_auth", "gw_stream_auth_2", "gw_stream_auth_3"]
    assert [s.nome_tmp for s in slots] == ["gw_stream", "gw_stream_2", "gw_stream_3"]   # cópias distintas
    assert len(avisos) == 1 and "falta" in avisos[0]


def test_le_do_ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_SESSOES_EXTRAS", "gw_stream_auth_2")
    assert len(ps.sessoes_configuradas(_pasta(tmp_path, "gw_stream_auth_2"))) == 2


# ── escolha ──────────────────────────────────────────────────────────────────
def _pool(n=3):
    rel = Relogio()
    slots = [ps.Slot(i, Path(f"s{i}.session"), f"t{i}", cliente=Cliente(i)) for i in range(n)]
    return ps.Pool(slots, relogio=rel), rel


def test_espalha_pelos_menos_ocupados():
    pool, _ = _pool()
    abertos = []
    for _ in range(6):
        s = pool.escolher()
        cm = pool.ocupar(s.cliente)
        cm.__enter__()
        abertos.append(cm)
    assert [s.em_uso for s in pool.slots] == [2, 2, 2]
    for cm in abertos[:2]:
        cm.__exit__(None, None, None)
    assert pool.escolher().em_uso == 1


def test_empate_vai_para_quem_serviu_menos_e_depois_a_principal():
    pool, _ = _pool()
    assert pool.escolher().indice == 0
    with pool.ocupar(pool.slots[0].cliente):
        pass
    assert pool.escolher().indice == 1


def test_ocupar_libera_mesmo_com_erro():
    pool, _ = _pool()
    with pytest.raises(RuntimeError):
        with pool.ocupar(pool.slots[1].cliente):
            raise RuntimeError("caiu")
    assert pool.slots[1].em_uso == 0 and pool.slots[1].servidos == 1


def test_castigada_sai_da_fila_e_volta_no_prazo():
    pool, rel = _pool(2)
    pool.castigar(pool.slots[0], 30, "FloodWait")
    assert pool.escolher().indice == 1
    with pool.ocupar(pool.slots[1].cliente):
        with pool.ocupar(pool.slots[1].cliente):
            assert pool.escolher().indice == 1          # mesmo ocupada, a castigada não entra
    rel.t += 31
    assert pool.escolher().indice == 0


def test_todas_castigadas_usa_a_que_volta_primeiro():
    pool, _ = _pool(2)
    pool.castigar(pool.slots[0], 100, "x")
    pool.castigar(pool.slots[1], 10, "x")
    assert pool.escolher().indice == 1


def test_resumo_nao_quebra_e_mostra_motivo_so_enquanto_vale():
    pool, rel = _pool(2)
    pool.castigar(pool.slots[1], 5, "FloodWait")
    r = pool.resumo()
    assert r[1]["motivo"] == "FloodWait" and r[1]["fora_por_s"] == 5 and r[0]["conectada"]
    rel.t += 6
    assert pool.resumo()[1]["motivo"] == ""
