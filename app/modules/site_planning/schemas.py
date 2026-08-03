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

from pydantic import BaseModel, ConfigDict, Field

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


# --- T3 yazma şemaları (DEĞİŞTİRME semantiği) ---
#
# Dört ucun DÖRDÜ de "değiştirme"dir: gövde ilgili kapsamın TAM kümesidir,
# gönderilmeyen kayıt SİLİNİR. Mockup'ta tek "Kaydet" düğmesi vardır (P97) —
# taslak/onay akışı, durum kolonu ya da kilitleme AÇILMAZ (spec §3). Sonraki
# okuyucu buraya durum makinesi EKLEMESİN.
#
# `project_id` HİÇBİR giriş şemasında YOKTUR: kapsam alanı şantiyeden KOPYALANIR.
# İstemciden alınsaydı görünür bir şantiyeye görünmez bir projenin satırı
# yazılabilirdi. `extra="forbid"` bunu sessiz yok saymak yerine 422 yapar.


class SitePlanRowInput(BaseModel):
    """`PUT …/plan/rows` gövdesinin tek satırı.

    `id` VARSA mevcut satır güncellenir, YOKSA yeni satır açılır. Kimlik gövdede
    taşınır çünkü etiketi değişen bir satırın hücreleri KORUNMALIDIR: doğal
    anahtarla eşleşseydi her yeniden adlandırma sil+ekle olur ve hücreler
    CASCADE ile giderdi (sessiz veri kaybı).
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    kind: PlanResourceKind
    # Ekipmanda NULL ZORUNLUDUR (spec §2) — korkuluk
    # `guards.EQUIPMENT_ROW_HAS_SECTION`.
    section_id: uuid.UUID | None = None
    label: str = Field(min_length=1, max_length=100)
    planned_worker_count: int | None = Field(default=None, ge=0)
    sort_order: int = 0


class SitePlanRowsSave(BaseModel):
    """⚠️ Gövde ŞANTİYENİN satır kümesinin TAMAMIDIR; geçmeyen satır SİLİNİR ve
    hücreleri CASCADE ile gider."""

    model_config = ConfigDict(extra="forbid")

    rows: list[SitePlanRowInput] = Field(default_factory=list)


class SitePlanRowSaved(BaseModel):
    """Kaydedilmiş satır. `cells` alanı YOKTUR (`SitePlanRowRead`ten farkı budur):
    bu uç haftadan bağımsızdır, boş bir `cells` listesi "hücre yok" YALANINI
    söylerdi."""

    id: uuid.UUID
    kind: PlanResourceKind
    section_id: uuid.UUID | None
    label: str
    planned_worker_count: int | None
    sort_order: int


class SitePlanRowsResult(BaseModel):
    """`PUT …/plan/rows` yanıtı — kaydedilen satırlar, okuma ucuyla AYNI sırada.

    Haftalık ızgara (`SitePlanWeek`) DÖNÜLMEZ: satır listesi haftadan bağımsızdır
    (uçta `week_start` yoktur) ve bir hafta uydurmak ekranın hangi haftayı
    gösterdiğine backend'in karar vermesi demek olurdu. Ekran yeni satır
    kimliklerini buradan alır, ızgarayı `GET …/plan` ile tazeler.
    """

    rows: list[SitePlanRowSaved]


class SitePlanCellInput(BaseModel):
    """`PUT …/plan/cells` gövdesinin tek hücresi.

    Hücrenin kendi `id`si YOKTUR: kimliği `(row_id, plan_date)` ikilisidir (UQ) —
    ızgarada bir satırın bir gününde tek hücre vardır.

    **Boş `text` hücreyi YOK SAYAR** (spec §2 "hücre yokluğu = plan yok"): ekranın
    boşalttığı hücre için boş metinli bir kayıt yazmak, "planlanmamış gün" ile
    "planı silinmiş gün"ü ayırt edilemez hâle getirirdi. Boşluklar kırpılır.
    """

    model_config = ConfigDict(extra="forbid")

    row_id: uuid.UUID
    plan_date: date
    text: str = Field(max_length=200)
    tag: PlanCellTag | None = None


class SitePlanCellsSave(BaseModel):
    """⚠️ Gövde YALNIZ `week_start` haftasının + o şantiyenin hücre kümesidir;
    geçmeyen hücre SİLİNİR. Başka haftaya/şantiyeye DOKUNULMAZ."""

    model_config = ConfigDict(extra="forbid")

    cells: list[SitePlanCellInput] = Field(default_factory=list)


class SitePlanGoalInput(BaseModel):
    """`PUT …/plan/goals` gövdesinin tek hedefi (P205-227).

    `week_start` gövdede YOKTUR — sorgu parametresinden gelir; iki kaynak olsaydı
    bir haftanın kaydetmesi gövdedeki tarihle başka bir haftaya taşabilirdi.

    `is_done` ile `status` AYRI alanlardır ve biri diğerinden TÜRETİLMEZ (spec §2).
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    note: str | None = None
    is_done: bool = False
    status: PlanGoalStatus
    sort_order: int = 0


class SitePlanGoalsSave(BaseModel):
    """⚠️ Gövde YALNIZ o haftanın hedef kümesidir; geçmeyen hedef SİLİNİR."""

    model_config = ConfigDict(extra="forbid")

    goals: list[SitePlanGoalInput] = Field(default_factory=list)


class SitePlanSprintSave(BaseModel):
    """`PUT …/plan/sprint` — aktif sprintin ADI (P107).

    `null`/boş ad = şantiyenin aktif sprinti YOK; kayıt SİLİNMEZ, `is_active`
    false'a çekilir (geçmiş sprint yan yana durabilir, kısmi UQ yalnız aktifleri
    kısıtlar). Tarih alanı YOKTUR — mockup göstermiyor (spec §2).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=150)
