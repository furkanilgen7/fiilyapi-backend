"""HTTP kodunu araç zarfına çeviren **TEK** dönüştürücü.

## Niye `reads/` altında değil

`tools/reads/` altında artık İKİ handler modülü var (`handlers.py` AI-0b'nin
altı aracı, `ai2bd.py` AI-2b+2d'nin on altısı — dosya 800 satır tavanını aştığı
için bölündü, `_journal.py` emsali). İkisi de bu çeviriciye ihtiyaç duyar ve
biri ötekinden import etseydi B15 ("handler'ı yalnız `catalog` import eder")
kırmızı olurdu: bekçi `"ai.tools.reads"` dizesini arar.

🔴 **İKİNCİ BİR KOPYA YAZILMADI.** Aynı korumanın ikinci kopyası bekçi değil,
**eşdeğer mutant yatağıdır**: 401'i üçüncü hâl saymayı bir kopyada unutmak
ötekini kırmızı yapmaz.
"""

from __future__ import annotations

from app.modules.ai.result import AracSonucu, NotFound, Restricted, ToolError


def kod_hali(durum: int, modul: str) -> AracSonucu | None:
    """HTTP kodunu zarfa çevirir. 🔴 401 ÜÇÜNCÜ HÂLDİR (B28/S19).

    `401` = oturum süresi doldu · `403` = yetkin yok · `404` = kayıt yok.
    Üçünü tek dala indiren bir handler ekranı ve modeli yalancı yapar.
    """
    if durum == 401:
        return ToolError("oturum_suresi_doldu")
    if durum == 403:
        return Restricted(modul)
    if durum == 404:
        return NotFound()
    if durum >= 400:
        return ToolError("ust_kaynak_hatasi")
    return None
