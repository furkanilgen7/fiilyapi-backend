"""Şantiye planlama korkulukları ve Türkçe hata metinleri (planlama spec §3).

`site_diary/guards.py` deseninin birebiri: metinler TEK yerde durur, router'a ya
da servise gömülü string YAZILMAZ.

`sites` modülünün "bulunamadı" cümlesi KOPYALANMAZ, İMPORT edilir: plan ucu
görünmeyen bir şantiye için `sites` ucundan FARKLI bir cümle dönerse, elinde bir
UUID olan kullanıcı iki uç arasındaki farktan kaydın var olduğunu çıkarabilir.
Aynı gerekçeyle `SECTION_MISMATCH` de `site_diary`den alınır — aynı kural iki
modülde iki farklı cümleyle konuşmamalıdır.

## T3 yazma korkulukları — hepsi 422'dir (`SiteValidationError`)

Gövde-içi çiftler puantajın 409'undan (`DuplicateError`) bilinçli olarak AYRILIR:
orada çakışma DB'de GERÇEKTEN vardır ve tek çare başka bir kayıttır; burada gövde
tek "Kaydet" düğmesinin (P97) TAM kümesidir ve kullanıcının düzelteceği şey bir
ALANDIR (etiketi ya da gününü değiştir). Modül içi tutarlılık kardeş modülle
tutarlılığa tercih edilir: dört ucun dördü de aynı sınıfı kullanır.

## "Bulunamadı" 422'dir, 404 DEĞİLDİR

Gövdedeki `id` bir SÜZGEÇ değil, düzeltilebilir bir ALANDIR (`site_diary`
`SECTION_MISMATCH` deseni). 404 verilseydi ekran "şantiye yok" ile "satır
kimliği eskimiş"i ayırt edemezdi. Var OLMAYAN kimlik ile BAŞKA şantiyenin/
haftanın kimliği AYNI cümleyi alır — kimlik varlığı sızdırılmaz.
"""

import uuid
from datetime import date

from app.modules.site_diary.guards import SECTION_MISMATCH
from app.modules.sites.guards import SITE_MISSING

__all__ = [
    "CELL_OUT_OF_WEEK_PREFIX",
    "DUPLICATE_CELL",
    "DUPLICATE_GOAL",
    "DUPLICATE_ROW",
    "EQUIPMENT_ROW_HAS_SECTION",
    "GOAL_UNKNOWN",
    "ROW_UNKNOWN",
    "SECTION_MISMATCH",
    "SITE_MISSING",
    "WEEK_START_NOT_MONDAY",
    "cell_key",
    "format_cell_out_of_week",
    "row_key",
]

# 422 — `week_start` haftanın Pazartesi'si DEĞİL. Sessizce Pazartesi'ye
# kaydırmak, ekranın istediğinden BAŞKA bir haftayı gösterdiğini fark
# edemeyeceği anlamına gelirdi; hafta gezinme okları (P103-105) da yanlış
# çıpadan ilerlerdi. Aynı gerekçe yazma uçlarında (T3) daha da ağırdır:
# kaydırılmış bir hafta, kullanıcının görmediği bir haftanın hücrelerini
# DEĞİŞTİRME semantiğiyle süpürürdü.
WEEK_START_NOT_MONDAY = "Hafta başlangıcı Pazartesi olmalıdır"

# 422 — gövdedeki satır kimliği bu ŞANTİYENİN satırı değil (ya da hiç yok).
# Kabul edilseydi satır sessizce şantiye DEĞİŞTİRİR, komşu ızgaradan kaybolurdu.
ROW_UNKNOWN = "Seçilen plan satırı bulunamadı"

# 422 — gövdedeki hedef kimliği bu şantiyenin O HAFTAKİ hedefi değil. Hafta da
# kimliğin parçasıdır: kabul edilseydi hedef sessizce hafta değiştirirdi.
GOAL_UNKNOWN = "Seçilen haftalık hedef bulunamadı"

# 422 — aynı (tür, bölüm, etiket) üçlüsü gövdede birden fazla.
#
# ⚠️ T1'den DEVREDİLEN SINIR: `UQ (site_id, kind, section_id, label)` Postgres'te
# `section_id IS NULL` dalında FİİLEN ÇALIŞMAZ — NULL'lar birbiriyle çakışmaz.
# Yani ekipman satırlarında (spec §2: bölümü ZATEN NULL) ve bölümsüz ekip
# satırlarında tekilliği DB DEĞİL BU KORKULUK tutar. Kısmi tekil indeks açmak
# migration işi olurdu; DEĞİŞTİRME semantiğinde gövde zaten kümenin tamamı
# olduğu için doğrulama uygulama katmanında YETERLİDİR ve tek istekte net bir
# Türkçe mesaj verir.
DUPLICATE_ROW = "Aynı tür, bölüm ve etikete sahip birden fazla plan satırı gönderildi"

# 422 — aynı (satır, gün) ikilisi gövdede birden fazla. Boş metinli hücreler de
# SAYILIR: "sil" ile "yaz" aynı hücre için birlikte gelirse hangisinin kazandığı
# belirsizdir, sessizce birini seçmek veri kaybı riskidir.
DUPLICATE_CELL = "Aynı satır ve gün için gövdede birden fazla plan hücresi gönderildi"

# 422 — aynı hedef kimliği gövdede birden fazla.
DUPLICATE_GOAL = "Aynı haftalık hedef gövdede birden fazla kez gönderildi"

# 422 — ekipman satırına bölüm atanmış. Spec §2: ekipmanda `section_id` NULL'dur.
# Bölümlü bir ekipman satırı okuma tarafında `(kind, section_id)` gruplamasında
# AYRI bir başlık açar ve P158 "Makine & Ekipman" grubunu ikiye böler.
EQUIPMENT_ROW_HAS_SECTION = "Makine ve ekipman satırına bölüm atanamaz"

# 422 — hafta dışı hücre. Şablonun İLK parçası sabittir (test bu önekle eşleşir).
CELL_OUT_OF_WEEK_PREFIX = "Plan hücresi hafta dışında"
_CELL_OUT_OF_WEEK = (
    CELL_OUT_OF_WEEK_PREFIX + ": {plan_date}. Kaydedilen hafta {start} – {end}; "
    "başka bir haftanın hücresi bu istekle gönderilemez."
)


def format_cell_out_of_week(plan_date: date, start: date, end: date) -> str:
    return _CELL_OUT_OF_WEEK.format(
        plan_date=plan_date.isoformat(), start=start.isoformat(), end=end.isoformat()
    )


def row_key(
    kind: str, section_id: uuid.UUID | None, label: str
) -> tuple[str, uuid.UUID | None, str]:
    """Satırın DOĞAL anahtarı — UQ ile BİREBİR aynı üçlü (şantiye zaten sabittir).

    Tek yerde tanımlıdır: gövde-içi çift kontrolü bu anahtarı kullanır. Etiket
    kırpılmış hâliyle karşılaştırılır — "Kalıpçı" ile "Kalıpçı " ızgarada aynı
    satırdır, DB'de iki farklı kayıt olurdu.
    """
    return (kind, section_id, label.strip())


def cell_key(row_id: uuid.UUID, plan_date: date) -> tuple[uuid.UUID, date]:
    """Hücrenin kimliği — UQ (row_id, plan_date) ile BİREBİR aynı ikili.

    Gövde-içi çift kontrolü ile mevcut kayıtla eşleme AYNI anahtarı kullanmazsa
    ikisi farklı şeyi "aynı hücre" sanar.
    """
    return (row_id, plan_date)
