"""Proje modulunun kullaniciya gorunen Turkce gerekcelerinin TEK yeri.

`audit/messages.py` deseninin aynisi: servise/router'a string gomulmez, boylece
ayni gerekce hem uctan hem testten ayni kaynaktan okunur ve metin degistiginde
tek noktada degisir.
"""

SHAREHOLDER_UNKNOWN = (
    "Gönderilen hissedar kaydı bu projede bulunamadı. "
    "Sayfayı yenileyip güncel hissedar listesiyle tekrar deneyin."
)

# T5 FINAL REVIEW bulgusu: ayni id listede iki kez gecerse birlestirme SESSIZCE
# tek satira cokuyordu (200 doner, ikinci girdinin adi kazanir, ilkinin orani
# kaybolur) — kullanicinin istedigi iki satirdan biri gerekcesiz yok olurdu.
# Bu, dilimin varlik sebebiyle (spec §4.1 "sessiz supurme YOK") ayni sinifta bir
# hatadir. Allocation ucu ayni sekil hatasini bir modul otede ZATEN reddediyor
# (`units.guards.DUPLICATE_IN_PAYLOAD`); hissedar listesi de ayni kapiyi kurar.
SHAREHOLDER_DUPLICATE_IN_PAYLOAD = "Aynı hissedar listede birden çok kez var"


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
