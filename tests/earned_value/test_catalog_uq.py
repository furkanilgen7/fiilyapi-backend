"""KATALOG-UQ — normalize katalog tekilligi DB DUZEYINDE (EV-BORC-5'in emniyet agi).

EV-BORC-5 tekilligi yalniz servis SELECT'iyle sinadi; DB UQ'su BIREBIR (harf duyarli)
kaldi. Servisi atlayan her yazar (yaris, ORM dogrudan yazma, eski konteyner) "Beton" ve
"BETON"u yan yana yazabilirdi. Artik `name_key`/`uom_key` kolonlarini UYGULAMA yazar
(`labels.normalize_label`, TEK kaynak) ve DB yalniz ESITLIGI zorlar:
`uq_ev_catalog_items_disc_name_key_uom_key`.

Neden ifade indeksi DEGIL (KATALOG-UQ raporu K1/K2): Postgres `lower()` DB'nin
LC_CTYPE'ina bagli ("C"de 1381 kod noktasi Python'dan farkli), libc'de Yunan final
sigma'yi bilmez ve glibc'nin Unicode surumu Python'unkinden farkli. Duz varchar
esitligi (deterministik harmanlama) ise bayt esitligidir: ctype'tan bagimsiz.

Buradaki ciftler K1 olcumunden gelir: `esit` ciftlerde Python ayni anahtari uretir →
DB REDDETMELI; `farkli` ciftlerde Python farkli anahtar uretir → DB KABUL ETMELI (DB,
Python'dan fazla normalize etmemeli).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.earned_value.labels import normalize_label
from app.modules.earned_value.models import EvDiscipline

UQ = "uq_ev_catalog_items_disc_name_key_uom_key"

#: (a, b, uom_a, uom_b) — Python'a gore AYNI anahtar.
ESIT = {
    "buyuk-kucuk": ("Beton döküm", "BETON DÖKÜM", "m³", "m³"),
    "bosluk": ("Beton döküm", "  beton \t  döküm ", "m³", "m³"),
    "ust-simge-birim": ("Beton döküm", "beton döküm", "m³", "M3"),
    "turkce-noktali-I": ("kireç sıva", "KİREÇ SIVA", "m²", "m2"),
    "turkce-noktasiz-I": ("ışık", "IŞIK", "ad", "AD"),
    "latin-Y-umlaut": ("ÿ", "Ÿ", "ad", "ad"),
    "latin-O-slash": ("Øre", "øre", "ad", "ad"),
    "yunan-final-sigma": ("ΟΔΟΣ", "οδος", "ad", "ad"),
    "kiril": ("БЕТОН", "бетон", "ad", "ad"),
    "buyuk-eszett": ("STRAẞE", "straße", "ad", "ad"),
    "nbsp": ("a b", "a b", "ad", "ad"),
    "ideografik-bosluk": ("a　b", "a b", "ad", "ad"),
    "u001c-bosluk-sayilir": ("a\u001cb", "a b", "ad", "ad"),
    "kelvin": ("K", "k", "ad", "ad"),
    # KATALOG-UQ madde 1: NFC normalizasyonu — "é" (U+00E9, NFC) ile "e"+U+0301 (NFD) ayni anahtar.
    "nfc-nfd-esit": ("é", "é", "ad", "ad"),
    # Sifir genislikli karakterler SILINIR (bosluga cevrilmez, iki harf bitisir), bosluk DEGIL.
    "zwsp-silinir": ("a​b", "ab", "ad", "ad"),
    "zwnj-silinir": ("Be‌ton", "Beton", "ad", "ad"),
    "zwj-silinir": ("Be‍ton", "Beton", "ad", "ad"),
    "bom-silinir": ("Be﻿ton", "Beton", "ad", "ad"),
}

#: Python'a gore FARKLI anahtar — DB de ayri kabul etmeli.
FARKLI = {
    "yunan-sigma-final-degil": ("ΟΔΟΣ", "οδοσ", "ad", "ad"),
    "eszett-ss": ("straße", "strasse", "ad", "ad"),
    "ust-simge-1": ("m¹", "m1", "ad", "ad"),
    "birim-farkli": ("Beton döküm", "Beton döküm", "m³", "ton"),
}


def _violates(exc: IntegrityError) -> bool:
    """Dogru sebep: BU kisit (baska bir NOT NULL/FK/CHECK degil)."""
    return f'unique constraint "{UQ}"' in str(exc)


@pytest.mark.parametrize(("a", "b", "ua", "ub"), list(ESIT.values()), ids=list(ESIT))
async def test_KQ_db_rejects_python_equal_pair(
    seeded_db: AsyncSession, kab: EvDiscipline, katalog_fabrikasi, a, b, ua, ub
) -> None:
    assert (normalize_label(a), normalize_label(ua)) == (normalize_label(b), normalize_label(ub))
    await katalog_fabrikasi(kab, a, uom=ua)
    with pytest.raises(IntegrityError) as exc:
        await katalog_fabrikasi(kab, b, uom=ub)
    assert _violates(exc.value), exc.value


@pytest.mark.parametrize(("a", "b", "ua", "ub"), list(FARKLI.values()), ids=list(FARKLI))
async def test_KQ_db_accepts_python_different_pair(
    seeded_db: AsyncSession, kab: EvDiscipline, katalog_fabrikasi, a, b, ua, ub
) -> None:
    assert (normalize_label(a), normalize_label(ua)) != (normalize_label(b), normalize_label(ub))
    await katalog_fabrikasi(kab, a, uom=ua)
    await katalog_fabrikasi(kab, b, uom=ub)


async def test_KQ_same_key_in_other_discipline_is_allowed(
    seeded_db: AsyncSession, kab: EvDiscipline, disiplin_fabrikasi, katalog_fabrikasi
) -> None:
    duv = await disiplin_fabrikasi("DUV", "Duvar")
    await katalog_fabrikasi(kab, "Tuğla")
    await katalog_fabrikasi(duv, "TUĞLA")


async def test_KQ_orm_rename_into_variant_is_rejected_by_db(
    seeded_db: AsyncSession, kab: EvDiscipline, katalog_fabrikasi
) -> None:
    """Anahtar ad/birim YAZILDIGINDA yeniden turer: servisi atlayan ORM yeniden adlandirmasi da
    DB'de takilir (bayat anahtar olsaydi "Kalıp"in anahtari kalir, cift gecerdi)."""
    await katalog_fabrikasi(kab, "Beton döküm")
    kalip = await katalog_fabrikasi(kab, "Kalıp")
    kalip.name = "BETON  DÖKÜM"
    with pytest.raises(IntegrityError) as exc:
        await seeded_db.flush()
    assert _violates(exc.value), exc.value


async def test_KQ_uom_change_into_variant_is_rejected_by_db(
    seeded_db: AsyncSession, kab: EvDiscipline, katalog_fabrikasi
) -> None:
    await katalog_fabrikasi(kab, "Beton döküm", uom="m³")
    ton = await katalog_fabrikasi(kab, "Beton döküm", uom="ton")
    ton.uom = "M3"
    with pytest.raises(IntegrityError) as exc:
        await seeded_db.flush()
    assert _violates(exc.value), exc.value


async def test_KQ_stored_keys_are_python_normalize_byte_for_byte(
    seeded_db: AsyncSession, kab: EvDiscipline, katalog_fabrikasi
) -> None:
    """DB'deki anahtar, Python `normalize_label` ciktisinin KENDISIDIR (DB normalize etmez)."""
    names = sorted({v for pair in (*ESIT.values(), *FARKLI.values()) for v in pair[:2]})
    for i, name in enumerate(names):
        await katalog_fabrikasi(kab, name, uom=f"U{i} ³")
    rows = (
        await seeded_db.execute(
            text(
                "SELECT name, uom, name_key, uom_key FROM ev_catalog_items WHERE discipline_id = :d"
            ),
            {"d": kab.id},
        )
    ).all()
    assert len(rows) == len(names)
    for name, uom, name_key, uom_key in rows:
        assert (name_key, uom_key) == (normalize_label(name), normalize_label(uom)), name


def test_KQ_normalize_is_idempotent_for_all_pairs() -> None:
    """normalize(normalize(x)) == normalize(x) — ESIT/FARKLI ciftlerinde (kod noktasi
    genisligi `test_kq_catalog_uq_migration.py`da; burada senaryo duzeyinde)."""
    values = {v for pair in (*ESIT.values(), *FARKLI.values()) for v in pair[:2]}
    for value in values:
        once = normalize_label(value)
        assert normalize_label(once) == once, value
