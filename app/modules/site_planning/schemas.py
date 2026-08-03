"""Şantiye planlama okuma şemaları — planlama spec §2, §3 · mockup P (Planlama).

Alanların TAMAMI mockup'tan gelir (WORKFLOW §3):

| Alan | Kaynak |
|---|---|
| `week_start` / `week_end` / `days` | P107 "21 – 27 Temmuz 2026" şeridi + P110-119 gün başlıkları |
| `days[].is_weekend` | P118-119 Cmt/Paz sütunlarının vurgusu (`#fef9f0`) |
| `groups[].section_name` | P125 "Kat 6–10 Kaba" grup başlığı |
| `groups[].section_manager_name` | P126 "Bölüm sorumlusu: Sercan Öztürk" |
| `groups[].kind` = equipment | P158 "Makine & Ekipman" grubu |
| `rows[].label` / `planned_worker_count` | P128 "Kalıpçı (14)" |
| `cells[].text` / `tag` | P129-179 hücre metni + rengi |
| `goals[]` | P203-227 "🎯 Haftalık Hedefler" |
| `active_sprint` | P108 "Aktif Sprint: Kat 8–9 Tamamlama" |

**Malzeme planı kartı (P185-201) BU ŞEMADA YOKTUR** (spec §5/§6 S5): stok ve
satınalma dilimlerine pending'dir, frontend kartı "pending" basar.

**Plan-gerçekleşen kıyası YOKTUR** (spec §5): mockup'ta da yok; türev rapor
katmanının işidir. Sonraki okuyucu buraya "gerçekleşen" alanı EKLEMESİN.
"""

import uuid
from datetime import date

from pydantic import BaseModel

from app.modules.site_planning.models import PlanCellTag, PlanGoalStatus, PlanResourceKind


class SitePlanDay(BaseModel):
    """Haftanın bir gün sütunu — TÜREV iskelet (P110-119).

    Gün listesi hücrelerden DEĞİL takvimden üretilir: planı olmayan gün de bir
    sütundur, aksi hâlde ızgara haftanın ortasında delik gösterirdi.
    """

    plan_date: date
    # Hafta sonu vurgusu TÜREVDİR (spec §3): DB'de kolon AÇILMAZ. Ekran bunu
    # kendi de hesaplayabilirdi ama o zaman "hafta sonu" tanımı iki yerde
    # yaşardı; tek kaynak backend'dir.
    is_weekend: bool


class SitePlanCellRead(BaseModel):
    """Izgara hücresi (P129-179). `row_id` TEKRARLANMAZ — hücre satırın içindedir."""

    plan_date: date
    text: str
    tag: PlanCellTag | None


class SitePlanRowRead(BaseModel):
    """Izgara satırı + YALNIZ istenen haftanın hücreleri.

    `cells` SEYREKTİR: planı olmayan gün hücre ÜRETMEZ (spec §2 "hücre yokluğu =
    plan yok"). Gün iskeleti `days`ten gelir, boş hücre uydurulmaz.
    """

    id: uuid.UUID
    kind: PlanResourceKind
    section_id: uuid.UUID | None
    label: str
    planned_worker_count: int | None
    sort_order: int
    cells: list[SitePlanCellRead]


class SitePlanGroup(BaseModel):
    """Izgaranın grup başlığı + satırları (P125-126 / P158).

    Gruplama anahtarı `(kind, section_id)` İKİLİSİDİR, tek başına `section_id`
    değil: ekipman satırlarının bölümü zaten NULL'dur (spec §2) ve mockup onları
    AYRI bir başlık altında gösterir — bölümsüz bir ekip satırıyla aynı gruba
    düşerlerse "Makine & Ekipman" başlığı kaybolur.

    `section_name`/`section_manager_name` bölümün ANLIK GÖRÜNTÜSÜ değil canlı
    değeridir (join): bölüm adı değişince ızgara başlığı da değişmelidir.
    """

    kind: PlanResourceKind
    section_id: uuid.UUID | None
    section_name: str | None
    section_manager_name: str | None
    rows: list[SitePlanRowRead]


class SitePlanGoalRead(BaseModel):
    """Haftalık hedef (P205-227).

    `is_done` (checkbox, P207) ile `status` (rozet, P209) AYRI alanlardır ve
    biri diğerinden TÜRETİLMEZ — mockup ikisini bağımsız gösterir.
    """

    id: uuid.UUID
    title: str
    note: str | None
    is_done: bool
    status: PlanGoalStatus
    sort_order: int


class SitePlanSprintRead(BaseModel):
    """Aktif sprint (P108). Tarih alanı YOKTUR — mockup göstermiyor (spec §2)."""

    id: uuid.UUID
    name: str


class SitePlanWeek(BaseModel):
    """Planlama ekranının bir haftalık tamamı.

    Şantiye/proje adları başlık şeridi içindir; ekran ikinci bir istek atmasın.
    """

    site_id: uuid.UUID
    site_name: str
    project_id: uuid.UUID
    project_name: str
    week_start: date
    # TÜREV (`week_start + 6`): P107 şeridi aralığı yazar, iki uç da tek
    # kaynaktan gelsin.
    week_end: date
    days: list[SitePlanDay]
    groups: list[SitePlanGroup]
    goals: list[SitePlanGoalRead]
    # Aktif sprint YOKSA `null` — geçmiş sprint şeride yazılmaz.
    active_sprint: SitePlanSprintRead | None
