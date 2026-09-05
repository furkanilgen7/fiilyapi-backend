"""BC-3 belge ↔ varlık bağı korkulukları ve Türkçe hata metinleri.

`documents/guards.py` deseninin kardeşi: metinler TEK yerde durur, router'a ya
da servise gömülü string YAZILMAZ. Sahibin "bulunamadı" cümleleri KOPYALANMAZ,
İMPORT edilir (`sites` · `units` · `sales` · `contracts` guard'ları): bağ ucu
görünmeyen bir bölüm için `GET /sections/{id}`den FARKLI bir cümle dönerse,
elinde UUID olan kullanıcı iki uç arasındaki farktan kaydın var olduğunu
çıkarabilir.

| Durum | Kod | Sınıf |
|---|---|---|
| Görünmeyen ya da var olmayan sahip | 404 | `NotFoundError` (sahibin kendi cümlesi) |
| Görünmeyen ya da var olmayan bağ satırı | 404 | `NotFoundError` |
| `type_id` yok YA DA başka bölmenin tipi | 422 | `DocumentValidationError` |
| `document_id` yok YA DA başka projenin belgesi | 422 | `DocumentValidationError` |

**422 çiftlerinde var OLMAYAN kimlik ile BAŞKA kapsamın kimliği AYNI cümleyi
alır** — kimlik varlığı sızdırılmaz (`documents.SITE_NOT_IN_PROJECT` gerekçesi).
`type_id`/`document_id` gövdedeki düzeltilebilir ALAN DEĞERLERİDİR, istenen
kaynak sahiptir; bu yüzden 404 DEĞİL 422.
"""

from app.modules.contracts.guards import CONTRACT_MISSING
from app.modules.sales.guards import SALE_MISSING
from app.modules.sites.guards import SECTION_MISSING
from app.modules.units.guards import UNIT_MISSING

__all__ = [
    "CONTRACT_MISSING",
    "DOCUMENT_NOT_IN_SCOPE",
    "LINK_MISSING",
    "SALE_MISSING",
    "SECTION_MISSING",
    "SLOT_TYPE_INVALID",
    "UNIT_MISSING",
]

# 404 — görünmeyen sahibin bağı ile var olmayan bağ kimliği AYNI gövdeyi alır.
# Bağın görünürlüğü SAHİBİNİNKİYLE AYNIDIR; ayrı bir kapı yoktur (equipment
# `_visible_document` deseni).
LINK_MISSING = "Belge bağı bulunamadı"

# 422 — `type_id` yok YA DA başka bölmenin tipi (örn. satış slotu bir bölüme).
# DB de bileşik FK ile reddeder (`fk_<tablo>_type_scope`); bu satır o ihlali
# 500 yerine okunur bir 422'ye çevirir — İKİNCİ kat, tek kat değil.
SLOT_TYPE_INVALID = "Seçilen belge slotu bu kayıt için geçerli değil"

# 422 — `document_id` yok YA DA künyesinin `project_id`si sahibin türetilen
# projesinden farklı. Kabul edilseydi kullanıcı gördüğü bir belgeyi başka
# projenin kaydına asabilir, `visible_projects` süzgeci bağ üzerinden delinirdi.
DOCUMENT_NOT_IN_SCOPE = "Seçilen belge bu kaydın projesinde değil"
