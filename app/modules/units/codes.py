"""Blok kodu uretiminin SAF cekirdegi (spec §3.2, kullanici karari 4).

`summary.py` / `bulk.py` ile ayni gerekce: "A Blok" → `A` sorusu veritabanina,
oturuma ve yetkiye dokunmadan cevaplanabilmelidir. Bu modulde veritabani
oturumu YOKTUR ve olmamalidir — proje ici benzersizligi cozen fonksiyon bile
kullanilan kodlarin KUMESINI disaridan alir, sorguyu kendi atmaz.

`PRJ-{YYYY}-{NNN}` / `SNT-{YYYY}-{NNN}` deseni BURADA KULLANILMAZ (spec §3.2):
TU 159-165 unite numaralarini blok koduna bagliyor (`C-1`, `C-4`), uzun bir kod
unite numarasini `SNT-2026-003-1` yapardi.
"""

import re

__all__ = [
    "effective_block_code",
    "resolve_block_code",
]

# `blocks.code` sutunu `String(20)` — uretilen kod sutunu ASLA asmaz.
_MAX_CODE_LENGTH = 20
_WORD_SEPARATOR = "-"

# Adi tamamen "Blok" olan blogun geri dusus kodu: `B1`, `B2`, ... (spec §3.2/4).
_FALLBACK_PREFIX = "B"
_FALLBACK_PATTERN = re.compile(rf"^{_FALLBACK_PREFIX}(\d+)$")

# Kodun kendisi zaten ad oldugu icin ATILIR — "A Blok" ile "A" ayni kodu verir.
_DROPPED_WORDS = frozenset({"BLOK", "BLOCK"})

# `importer._LETTER_FOLD` DESENI, ama AYRI sozluk: oradaki katlama basliklari
# KUCUK harfe indirger (eslestirme icin), buradaki kod BUYUK harf uretir.
_TURKISH_FOLD = str.maketrans(
    {
        "Ç": "C",
        "ç": "C",
        "Ğ": "G",
        "ğ": "G",
        "İ": "I",
        "I": "I",
        "ı": "I",
        "i": "I",
        "Ö": "O",
        "ö": "O",
        "Ş": "S",
        "ş": "S",
        "Ü": "U",
        "ü": "U",
    }
)
_NON_CODE_CHARS = re.compile(r"[^A-Z0-9]+")


def _derive_block_code(name: str) -> str:
    """Blok adindan kisa kod uretir; uretilemezse **bos** doner (spec §3.2).

    Geri dusus (`B1`) BURADA yapilmaz: sirali kod projede kullanilan kodlari
    bilmeyi gerektirir ve bu fonksiyonun saf kalmasi, "A Blok" → `A` kuralinin
    tek basina test edilebilmesi demektir.
    """
    folded = name.translate(_TURKISH_FOLD).upper()
    words = [word for word in _NON_CODE_CHARS.split(folded) if word and word not in _DROPPED_WORDS]
    return _WORD_SEPARATOR.join(words)[:_MAX_CODE_LENGTH]


def _next_fallback_code(taken: set[str]) -> str:
    """`B1`, `B2`, ... — SAYIMLA DEGIL maksimum+1 (`_next_site_code` deseni).

    Silinen kod yeniden kullanilmaz; sayimla uretilseydi bir blok silindiginde
    yeni blok eski bir kodu devralirdi.
    """
    highest = 0
    for code in taken:
        match = _FALLBACK_PATTERN.match(code)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return f"{_FALLBACK_PREFIX}{highest + 1}"


def resolve_block_code(name: str, taken: set[str]) -> str:
    """Proje icinde BENZERSIZ kod uretir (spec §3.2 adim 4-5).

    `taken` projede halihazirda kullanilan kodlardir; cagiran (servis) verir.
    Cakisma `-2`, `-3` ... eki alir ve ek sonrasi da 20 karakteri ASMAZ.
    """
    base = _derive_block_code(name)
    if not base:
        return _next_fallback_code(taken)
    if base not in taken:
        return base
    attempt = 2
    while True:
        suffix = f"{_WORD_SEPARATOR}{attempt}"
        candidate = f"{base[: _MAX_CODE_LENGTH - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        attempt += 1


def effective_block_code(code: str | None, name: str) -> str:
    """Kodu **NULL** olan blokta jetonun ANLIK karsiligi (spec §3.2, karar 8).

    Canli bloklarin `code` sutunu NULL dogar ve NULL kalir — backfill
    migration'i YOKTUR. Toplu uretimin `{Blok}` jetonu bu blokta bos kalmasin
    diye kod ANLIK turetilir ve **SAKLANMAZ**: ikinci bir otorite dogmaz, cunku
    cagrilan fonksiyon `_derive_block_code`'un ta kendisidir — blok bir kez
    duzenlenip kodu kalicilastiginda cikti birebir aynidir.
    """
    if code:
        return code
    return _derive_block_code(name) or _FALLBACK_PREFIX
