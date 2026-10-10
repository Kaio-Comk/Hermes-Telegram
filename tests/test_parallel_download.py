import asyncio
import os
from types import SimpleNamespace

from tgmediakit.parallel_download import BLOCK, download_parallel


class FakeClient:
    def __init__(self, data: bytes, fail_at: int | None = None):
        self.data, self.fail_at, self.fallback_used = data, fail_at, False

    async def iter_download(self, doc, offset, request_size, limit):
        if self.fail_at is not None and offset == self.fail_at:
            raise RuntimeError("boom")
        await asyncio.sleep(0)
        yield self.data[offset:offset + request_size]

    async def download_media(self, msg, dest, progress_callback=None):
        self.fallback_used = True
        with open(dest, "wb") as f:
            f.write(self.data)


def _msg(n):
    return SimpleNamespace(document=SimpleNamespace(size=n), chat_id=1, id=1)


def test_arquivo_sai_identico_e_em_ordem(tmp_path):
    data = os.urandom(BLOCK * 11 + 123)
    c = FakeClient(data)
    dest = tmp_path / "x.mp4"
    asyncio.run(download_parallel(c, _msg(len(data)), dest, connections=4))
    assert dest.read_bytes() == data and not c.fallback_used


def test_falha_numa_faixa_cai_no_download_classico(tmp_path):
    data = os.urandom(BLOCK * 10)
    c = FakeClient(data, fail_at=BLOCK * 3)
    dest = tmp_path / "y.mp4"
    asyncio.run(download_parallel(c, _msg(len(data)), dest, connections=4))
    assert c.fallback_used and dest.read_bytes() == data


def test_arquivo_pequeno_usa_o_caminho_simples(tmp_path):
    data = os.urandom(1000)
    c = FakeClient(data)
    asyncio.run(download_parallel(c, _msg(len(data)), tmp_path / "z", connections=4))
    assert c.fallback_used
