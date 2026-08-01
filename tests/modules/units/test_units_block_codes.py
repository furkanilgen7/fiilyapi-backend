"""P3.1 T4 — blok kodu uretimi (spec §3.2).

Kod uretimi SAF bir cekirdektir: "A Blok" → "A" sorusu veritabanina, oturuma ve
yetkiye dokunmadan cevaplanabilmelidir (`bulk.py` / `summary.py` ile ayni
gerekce). Proje ici benzersizlik de saf tutulur — cagiran, projede KULLANILAN
kodlarin kumesini verir; karar mekanizmasi DB bilmez.
"""

import inspect

import pytest

from app.core.errors import DuplicateError
from app.modules.sites.models import Site
from app.modules.units import codes, guards, repository
from app.modules.units.codes import (
    _derive_block_code,
    effective_block_code,
    resolve_block_code,
)
from app.modules.units.models import Block


async def _site(session, project, code: str = "SANTIYE-1", name: str = "Merkez") -> Site:
    site = Site(project_id=project.id, code=code, name=name)
    session.add(site)
    await session.flush()
    return site


async def _block(session, project, site, name: str, **kwargs) -> Block:
    block = Block(project_id=project.id, site_id=site.id, name=name, **kwargs)
    session.add(block)
    await session.flush()
    return block


# --- Ad kisaltma (spec §3.2, kullanici karari 4) ---


def test_ad_kisaltilir_a_blok():
    """BE 71: "A Blok" → `A`. `PRJ-`/`SNT-` deseni KULLANILMAZ (spec §3.2)."""
    assert _derive_block_code("A Blok") == "A"


def test_ad_kisaltilir_c_blok():
    """TU 159-165 unite numaralari koda baglidir: `C-1`, `C-4`."""
    assert _derive_block_code("C Blok") == "C"


def test_turkce_karakter_katlanir():
    """Ç→C, Ğ→G, İ/I/ı→I, Ö→O, Ş→S, Ü→U — kod ASCII kalir."""
    assert _derive_block_code("Şantiye Ğ Blok") == "SANTIYE-G"
    assert _derive_block_code("Yeşilvadi C") == "YESILVADI-C"


def test_blok_kelimesi_atilir_zemin():
    """ "Blok"/"Block" kelimesi atilir, kalan sozcuk kod olur (KY 308 "Zemin")."""
    assert _derive_block_code("Zemin") == "ZEMIN"
    assert _derive_block_code("Zemin Blok") == "ZEMIN"


def test_noktalama_ve_bosluk_tire_olur():
    assert _derive_block_code("2. Etap A") == "2-ETAP-A"


def test_yirmi_karaktere_kirpilir():
    """Sutun `String(20)`: uretilen kod ASLA sutunu asmaz."""
    result = _derive_block_code("Kuzey Yakasi Prestij Konutlari Etap")
    assert result == "KUZEY-YAKASI-PRESTIJ"
    assert len(result) == 20


def test_ad_tamamen_blok_ise_bos_doner():
    """Saf cekirdek geri dusus URETMEZ — bos doner, sirali kodu cagiran secer."""
    assert _derive_block_code("Blok") == ""
    assert _derive_block_code("   ") == ""


# --- Proje ici cozum (spec §3.2 adim 4-5) ---


def test_bos_kalirsa_sirali_geri_dusus():
    """Ad tamamen "Blok" ise: `B1`, sonra `B2` (proje ici maksimum+1)."""
    assert resolve_block_code("Blok", set()) == "B1"
    assert resolve_block_code("Blok", {"B1"}) == "B2"
    # Silinen kod yeniden kullanilmaz: maksimum+1, sayim degil.
    assert resolve_block_code("Blok", {"B1", "B3"}) == "B4"


def test_proje_ici_cakisma_eki_alir():
    """Ayni projede ikinci "A Blok" → `A-2`, ucuncusu `A-3`."""
    assert resolve_block_code("A Blok", set()) == "A"
    assert resolve_block_code("A Blok", {"A"}) == "A-2"
    assert resolve_block_code("A Blok", {"A", "A-2"}) == "A-3"


def test_cakisma_eki_yirmi_karakteri_asmaz():
    base = _derive_block_code("Kuzey Yakasi Prestij Konutlari")
    assert len(resolve_block_code("Kuzey Yakasi Prestij Konutlari", {base})) <= 20


def test_farkli_projede_ayni_kod_serbest():
    """Benzersizlik PROJE ICIDIR: baska projede kullanilan kod burada engel degil."""
    assert resolve_block_code("A Blok", set()) == "A"


# --- §0.B: kodu NULL olan blokta ANLIK turetme ---


def test_effective_block_code_kodu_varsa_aynen_doner():
    assert effective_block_code("YV-C", "C Blok") == "YV-C"


def test_effective_block_code_kod_yoksa_addan_turetir():
    """Spec §3.2 karar 8: canli bloklarin `code`'u NULL kalir; toplu uretimin
    `{Blok}` jetonu ANLIK turetilir ve sonuc SAKLANMAZ (ikinci otorite dogmaz —
    cagrilan fonksiyon ayni saf fonksiyondur)."""
    assert effective_block_code(None, "C Blok") == "C"
    assert effective_block_code("", "A Blok") == "A"


def test_effective_block_code_ad_da_bos_kalirsa_sabit_geri_dusus():
    """Adi tamamen "Blok" olan kodsuz blok: jeton bos kalmaz."""
    assert effective_block_code(None, "Blok") == "B"


# --- Sozlesme ---


def test_derive_saf_fonksiyondur_dbsiz():
    """`codes.py` DB'ye DOKUNMAZ: kod uretimi oturumdan bagimsiz test edilebilir."""
    source = inspect.getsource(codes)
    assert "sqlalchemy" not in source
    assert "session" not in source.lower()


# --- Proje ici benzersizlik korkulugu (spec §3.2, §8.3) ---


async def test_project_block_codes_null_kodlari_atlar(db_session, project_factory):
    """Kodu NULL olan bloklar kumeye GIRMEZ: `None` bir kod degildir ve
    `resolve_block_code`'un cakisma kontrolunu kirletirdi."""
    project = await project_factory("T4-1")
    site = await _site(db_session, project)
    await _block(db_session, project, site, "A Blok", code="A")
    await _block(db_session, project, site, "B Blok")

    assert await repository.project_block_codes(db_session, project.id) == {"A"}


async def test_ensure_block_code_unique_cakismada_409(db_session, project_factory):
    project = await project_factory("T4-2")
    site = await _site(db_session, project)
    await _block(db_session, project, site, "A Blok", code="A")

    with pytest.raises(DuplicateError) as excinfo:
        await guards.ensure_block_code_unique(db_session, project.id, "A")

    assert str(excinfo.value) == guards.DUPLICATE_BLOCK_CODE


async def test_ensure_block_code_unique_kendini_haric_tutar(db_session, project_factory):
    """PATCH'te blogun KENDI kodu cakisma sayilmaz."""
    project = await project_factory("T4-3")
    site = await _site(db_session, project)
    block = await _block(db_session, project, site, "A Blok", code="A")

    await guards.ensure_block_code_unique(db_session, project.id, "A", block.id)


async def test_ensure_block_code_unique_baska_projede_serbest(db_session, project_factory):
    """Benzersizlik PROJE ICIDIR (`uq_blocks_project_code`)."""
    first = await project_factory("T4-4")
    second = await project_factory("T4-5")
    site = await _site(db_session, first)
    await _block(db_session, first, site, "A Blok", code="A")

    await guards.ensure_block_code_unique(db_session, second.id, "A")
