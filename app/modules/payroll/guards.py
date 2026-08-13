"""Bordro korkulukları ve Türkçe hata METİNLERİ (İK-3).

`personnel/guards.py` deseninin aynısı: hata SINIFLARI `app/core/errors.py`de,
metinler modül içinde TEK KOPYA sabit olarak durur — aynı kuralı iki uçtan
farklı cümleyle anlatan bir modül, kullanıcıya iki farklı kural öğretir.
"""

#: 404 — görünmeyen ile var olmayan dönem AYIRT EDİLEMEZ (spec §6.8).
PERIOD_MISSING = "Bordro dönemi bulunamadı"

#: 409 — onaylanmış/ödenmiş dönemde yeniden hesap YOKTUR (spec §5).
PERIOD_LOCKED = "Onaylanmış veya ödenmiş dönem yeniden hesaplanamaz"

#: İzin anahtarı — `payroll` seed'de İLK GÜNDEN BERİ VARDIR
#: (`roles/seed_data.py:182`, `alembic/.../a477fdf00fdf...:88`). Yeni izin
#: modülü AÇILMAZ (spec S9, ST/`inventory` emsali) ve `seed_data.py`ye
#: DOKUNULMAZ. Okuma `view`, yazma `full`.
PERMISSION_MODULE = "payroll"

#: 404 — görünmeyen ile var olmayan satır AYIRT EDİLEMEZ (spec §6.8).
LINE_MISSING = "Bordro satırı bulunamadı"

#: 409 — bir ay için TEK bordro (UQ `(year, month)`, spec §4).
PERIOD_DUPLICATE = "Bu ay için bordro dönemi zaten açılmış"

#: 409 — S5 değişmezliği: ödeme izi geriye dönük düzeltilmez.
LINE_LOCKED = "Onaylanmış veya ödenmiş bordro satırı değiştirilemez"

#: 409 — S5'in dönem tarafı: onaylanmış dönemin toplamları raporlanmıştır.
PERIOD_LOCKED_FOR_EDIT = "Onaylanmış veya ödenmiş dönemin satırları değiştirilemez"

#: 409 — K2: taşeron satırı bordrodan ÖDENMEZ, bölüşümü de düzenlenmez.
LINE_EXCLUDED = (
    "Taşeron satırı bordrodan ödenmez: tutarı ve ödeme bölüşümü düzenlenemez, "
    "ödemesi taşeron hakedişi üzerinden yapılır"
)


#: 422 — S3 invariantı. Tutarlar metne KONUR: kullanıcı hangi kuruşun kaydığını
#: ekrandaki iki `input`a bakarak bulamaz.
def split_mismatch(bank: object, cash: object, net: object) -> str:
    return f"Banka ({bank}) + elden ({cash}) toplamı net tutara ({net}) eşit olmalıdır"


#: 422 — S4: neti hesaplanmamış satırda bölüşüm TANIMSIZDIR.
SPLIT_WITHOUT_NET = "Hesaplanamamış satırda ödeme bölüşümü yapılamaz; önce brüt tutarı girin"

#: 422 — ŞEF KARARI 2 (T2): kesintisi bilinmeyen brütten net türetilmez.
RATE_MISSING = "Bu personel tipi için dönemin yılına ait aktif kesinti oranı tanımlı değil"
