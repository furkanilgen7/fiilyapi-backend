"""Bordro korkulukları ve Türkçe hata METİNLERİ (İK-3).

`personnel/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`de,
metinler modül içinde TEK KOPYA sabit olarak durur — aynı kuralı iki uçtan
farklı cümleyle anlatan bir modül, kullanıcıya iki farklı kural öğretir.
"""

#: 404 — görünmeyen ile var olmayan dönem AYIRT EDİLEMEZ (spec §6.8).
PERIOD_MISSING = "Bordro dönemi bulunamadı"

#: 409 — onaylanmış/ödenmiş dönemde yeniden hesap YOKTUR (spec §5).
PERIOD_LOCKED = "Onaylanmış veya ödenmiş dönem yeniden hesaplanamaz"
