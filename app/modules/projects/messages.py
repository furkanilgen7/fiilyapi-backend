"""Proje modulunun kullaniciya gorunen Turkce gerekcelerinin TEK yeri.

`audit/messages.py` deseninin aynisi: servise/router'a string gomulmez, boylece
ayni gerekce hem uctan hem testten ayni kaynaktan okunur ve metin degistiginde
tek noktada degisir.
"""

SHAREHOLDER_UNKNOWN = (
    "Gönderilen hissedar kaydı bu projede bulunamadı. "
    "Sayfayı yenileyip güncel hissedar listesiyle tekrar deneyin."
)


def shareholder_has_units(names: list[str]) -> str:
    """P9 spec §4.1: atanmis unitesi olan hissedar listeden dusurulemez — 409.

    Sessiz supurme (ON DELETE SET NULL) yerine gerekce gosterilir ve kullaniciya
    izlemesi gereken sira soylenir: once uniteleri bosalt, sonra hissedari sil.
    """
    return (
        "Atanmış ünitesi olan hissedar listeden çıkarılamaz: "
        + ", ".join(names)
        + ". Önce bu hissedara atanmış ünitelerin hissedar atamasını kaldırın."
    )
