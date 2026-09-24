"""`sections.id`'yi hedefleyen FK'ların `ondelete` HARİTASI — donmuş bekçi (kayıt 114).

## Neden bu dosya var

Bu ayrım repoda ÜÇ ayrı yerde DÜZ METİNLE anlatılıyordu ve üçü de birbiriyle
ve bugünle çelişiyordu:

| metin | iddia | ölçüldüğünde |
|---|---|---|
| `alembic/versions/b4c5d6e7f8a9…:23-25` | "yedi FK ve YEDİSİ DE `SET NULL`" | yanlış |
| `app/modules/boq/models.py` (K2 notu) | "sekiz FK — yedisi `SET NULL`, biri CASCADE" | yanlış |
| bugünkü kod | — | **11 FK: 8 `SET NULL`, 3 CASCADE** |

🔴 Bu haritayı `grep -rn 'ForeignKey("sections.id"'` ile kurmaya çalışmak da
ÇÜRÜK bir ölçümdür ve bu dosya yazılırken FİİLEN yanılttı: kolon adı her zaman
`section_id` DEĞİLDİR (`personnel.assigned_section_id`), FK kendi tablosunu
gösterebilir (`sections.depends_on_section_id`) ve ORM özniteliğinin adı kolon
adından farklı olabilir. Doğru kaynak `Base.metadata`dır — `_olcum()` onu okur.

İkisi de YAZILDIKLARI GÜN doğruydu. Çürüdüler çünkü sayı ELLE tutuluyordu ve
yeni bir FK ekleyen hiçbir dilim onları güncellemek ZORUNDA değildi. Sayıyı
tazelemek kusuru KAPATMAZ, yalnız saatini ileri alır.

👉 Bu yüzden onarım bir SAYI DÜZELTMESİ değil, bir BEKÇİdir: harita
`Base.metadata`dan ÖLÇÜLÜR ve donmuş sınıflandırmayla karşılaştırılır. Yeni bir
`sections.id` FK'sı eklendiğinde bu test KIRILIR ve yazarı iki kovadan birini
BİLEREK seçmeye zorlar.

## Ayrımın kuralı (migration'ın gerekçesi, kalıcı)

* **`SET NULL`** — bölüm kaydın bir BİLGİ ALANIdır; bölüm silinse de kayıt
  kendi başına anlamlıdır (bir puantaj satırı, bir personel, bir sipariş).
* **CASCADE** — kaydın BAĞIMSIZ VARLIĞI YOKTUR; bölüm gidince cümle
  anlamsızlaşır (tahsis satırı "şu poz, şu bölüme, şu kadar" demekten ibarettir).

🔴 Migration docstring'i DÜZELTİLMEZ: migration yazıldığı günün fotoğrafıdır ve
geçmişi yeniden yazmak, o gün alınan kararın gerekçesini okunamaz kılar. Yaşayan
belge BURASIDIR; `boq/models.py` artık sayı taşımaz, bu dosyaya işaret eder.
"""

from __future__ import annotations

from app.core.db import Base

#: 🔴 DONMUŞ HARİTA — `(tablo, kolon) -> ondelete`. Elle sayı YOKTUR; yeni bir
#: FK bu sözlüğe BİLEREK eklenmeden test geçmez.
BEKLENEN: dict[tuple[str, str], str] = {
    # --- bölüm bir BİLGİ ALANI: kayıt bölümsüz de anlamlı ---
    ("personnel", "assigned_section_id"): "SET NULL",
    ("purchase_requests", "section_id"): "SET NULL",
    ("sections", "depends_on_section_id"): "SET NULL",
    ("site_diary_entries", "section_id"): "SET NULL",
    ("site_plan_rows", "section_id"): "SET NULL",
    ("stock_entry_lines", "section_id"): "SET NULL",
    ("subcontractor_progress_payments", "section_id"): "SET NULL",
    ("timesheet_entries", "section_id"): "SET NULL",
    # --- kaydın BAĞIMSIZ VARLIĞI YOK: bölümle birlikte gider ---
    ("boq_item_section_allocations", "section_id"): "CASCADE",
    ("section_documents", "section_id"): "CASCADE",
    ("section_milestones", "section_id"): "CASCADE",
    # PLN-B1: yaprak ayari "su kalem, su bolumde, su oran" demekten ibarettir — tahsis
    # (kalem × bolum) gibi. Donmus revizyon ETKILENMEZ: baseline bolum kimligini FK'siz
    # tutar ve agac snapshot'tan basilir (`earned_value/budget_snapshot.py`).
    ("ev_leaf_settings", "section_id"): "CASCADE",
    # PLN-B1: disiplin × bolum pencere EZMESI — bolumsuz ezme anlamsiz.
    ("ev_windows", "section_id"): "CASCADE",
}


def _olcum() -> dict[tuple[str, str], str]:
    """`sections.id`'yi hedefleyen HER FK — metadata'dan, elle liste YOK."""
    harita: dict[tuple[str, str], str] = {}
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.target_fullname == "sections.id":
                harita[(table.name, fk.parent.name)] = (fk.ondelete or "NO ACTION").upper()
    return harita


def test_sections_fk_haritasi_DONMUS_SINIFLANDIRMAYLA_AYNI() -> None:
    olculen = _olcum()

    eksik = {k: v for k, v in BEKLENEN.items() if k not in olculen}
    yeni = {k: v for k, v in olculen.items() if k not in BEKLENEN}
    sapan = {k: (BEKLENEN[k], v) for k, v in olculen.items() if k in BEKLENEN and BEKLENEN[k] != v}

    assert not yeni, (
        f"`sections.id`'yi hedefleyen YENİ FK: {yeni}. İki kovadan birini BİLEREK seç "
        "ve bu dosyanın başındaki kurala göre `BEKLENEN`e ekle — sayı ezberlenmez, "
        "sınıflandırma yazılır."
    )
    assert not eksik, f"`BEKLENEN`de var ama kodda YOK (FK kaldırılmış?): {eksik}"
    assert not sapan, f"`ondelete` DEĞİŞMİŞ (beklenen, ölçülen): {sapan}"


def test_iki_kova_da_BOS_DEGIL() -> None:
    """Pozitif kontrol: ayrımın KENDİSİ hâlâ yaşıyor.

    `BEKLENEN` tek kovaya çökerse yukarıdaki test yine yeşil kalır ama belgelenen
    ayrım ortadan kalkmış olur — bu iddia o günü kırmızıyla karşılar.
    """
    olculen = set(_olcum().values())
    assert "SET NULL" in olculen, "hiçbir FK `SET NULL` değil — ayrım çökmüş"
    assert "CASCADE" in olculen, "hiçbir FK CASCADE değil — ayrım çökmüş"
