import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Weather(str, enum.Enum):
    """Hava durumu (spec §2). E7'nin BEŞLİSİ kanoniktir; GK'nin dörtlüsü alt kümedir
    (GK'de `snowy` yok) — süperset seçildi, ekran kendi listesini süzer.

    "Yağışlı" rozeti (GK370) KOLON DEĞİLDİR — frontend `weather == rainy` türevidir.
    """

    sunny = "sunny"
    partly_cloudy = "partly_cloudy"
    cloudy = "cloudy"
    rainy = "rainy"
    snowy = "snowy"
    # PLN-B2.1 (B2-1): mockup `Şantiye - Günlük Kayıt (İlerleme)` İ:283-291 anahtarları.
    # Mevcut beş değer DEĞİŞMEZ (eşleme gerekmez); yalnız EKLEME — sözleşme kırılmaz.
    heavy_rain = "heavy_rain"  # "Sağanak"
    drizzle = "drizzle"  # "Hafif yağmur"
    windy = "windy"  # "Rüzgârlı"
    dusty = "dusty"  # "Tozlu"
    foggy = "foggy"  # "Sisli"


class DiaryStatus(str, enum.Enum):
    """Günlük kaydın durumu (spec §2). İKİ durum: hakediş evrakının dört durumlu
    onay makinesi burada YOKTUR — günlük ya taslaktır ya gönderilmiştir.

    E7'nin iki butonu (Taslak Kaydet / Gönder) bu ikiliyi birebir karşılar;
    GK'nin tek "Kaydet & Gönder" butonu ikisinin bileşimidir.
    """

    draft = "draft"
    submitted = "submitted"


class WorkerSource(str, enum.Enum):
    """İşçi kırılımının kaynağı — GK418-430 rozetleri (spec §2).

    Taşeron ADI bağlanmaz (mockup'ta seçici yok); `subcontractor` yalnız kaynağı
    işaretler, puantaj modülü gelince taşeron kaydına köprülenir.

    İK-3 (bordro) `freelance` ve `intern` değerlerini EKLEDİ: BY 243 "SERBEST
    MESLEK" ve BY 271 "STAJYER" bölümleri oran tablosunun DÖRT tip gerektirdiğini
    gösteriyor (spec §4, S2) ve İK-1 bu takası açıkça İK-3'e ertelemişti
    (`personnel/models.py` üstündeki not). Yeni bir `personnel_source` TİPİ
    AÇILMADI — aynı anlam kümesinin iki DB tipi doğardı (puantaj spec §2).

    `general` ("genel işçi", GK418-430) bordro tipi DEĞİLDİR: BY dört bölüm
    çiziyor, bu değerin oran satırı yoktur.
    """

    company = "company"
    subcontractor = "subcontractor"
    general = "general"
    freelance = "freelance"
    intern = "intern"


class SiteDiaryEntry(Base):
    """Günlük kayıt başlığı — (şantiye, gün) ikilisi (spec §2).

    UQ (site_id, entry_date): günde TEK kayıt. GK deseni budur; bölüm kırılımı
    satırda değil BAŞLIK etiketindedir (`section_id`), yani "aynı gün iki bölüm
    için iki kayıt" mümkün DEĞİLDİR.

    `project_id` şantiyeden türetilebilir ama her liste sorgusunda JOIN gerektirirdi
    — `visible_projects` süzgeci için şantiyeden kopyalanır (taşeron hakedişi deseni).

    Fotoğraf / planlama / malzeme kolonları YOKTUR (spec §5 pending).
    """

    __tablename__ = "site_diary_entries"
    __table_args__ = (
        UniqueConstraint("site_id", "entry_date", name="uq_site_diary_entries_site_date"),
        # PLN-B2.1 (B2-2): min/max sicaklik + ruzgar. Sinirlar semadaki alan
        # dogrulamasiyla BIREBIR (`schemas._TEMP_*`, `_WIND_MAX`).
        CheckConstraint(
            "temp_min_c IS NULL OR temp_min_c BETWEEN -60 AND 60",
            name="ck_site_diary_entries_temp_min_range",
        ),
        CheckConstraint(
            "temp_max_c IS NULL OR temp_max_c BETWEEN -60 AND 60",
            name="ck_site_diary_entries_temp_max_range",
        ),
        CheckConstraint(
            "temp_min_c IS NULL OR temp_max_c IS NULL OR temp_min_c <= temp_max_c",
            name="ck_site_diary_entries_temp_min_le_max",
        ),
        CheckConstraint(
            "wind_ms IS NULL OR wind_ms BETWEEN 0 AND 80",
            name="ck_site_diary_entries_wind_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # SET NULL: bolum silinse de gunluk kaydi ayakta kalir (bilgi alani, GK198).
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Hava/sicaklik/aciklama alanlari NULLABLE: taslak yarim doldurulabilir
    # (P6 `is_draft` gerekcesinin aynisi — zorunluluk `submit` katmanindadir).
    weather: Mapped[Weather | None] = mapped_column(Enum(Weather, name="weather"), nullable=True)
    # Sicaklik yalniz min/max'tir (PLN-B2.1, B2-2). Eski tek sicaklik kolonu
    # CLEAN-B2'de modelden ve yazicisindan kalkti. Kolonun DB'den dusmesi AYRI bir
    # migration'dir ve bu modelin canlida oldugu surumden SONRA gelir (genislet/daralt:
    # eski konteyner kolonu esliyorsa DROP penceresinde her SELECT'i 500 verir).
    temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    # m/s (mockup "Rüzgâr m/s"; km/s istemci türevi).
    wind_ms: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    work_done: Mapped[str | None] = mapped_column(Text, nullable=True)
    # E7 143 — GK'de yok, korunur (spec §2).
    chief_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ISG ucusu (GK444-447). NOT NULL + server_default false: "isaretlenmedi" =
    # "yapilmadi" kabul edilir, uc-durumlu bir belirsizlik acilmaz.
    safety_meeting_held: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    ppe_checked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    has_incident: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    incident_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DiaryStatus] = mapped_column(
        Enum(DiaryStatus, name="diary_status"),
        nullable=False,
        default=DiaryStatus.draft,
        server_default="draft",
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # DET-1.B: gonderen — `submitted_at` ile BIRLIKTE yazilir, reopen ikisini de temizler
    # (`transitions._stamp`). DET-1.B oncesi gonderimlerde NULL: denetim satirinda varlik
    # kimligi yok, metinden turetmek guvenilmez (geri doldurma YAPILMADI).
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # can_delete korkulugu (app/core/access.py) created_by + is_draft ister.
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lines: Mapped[list["SiteDiaryLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        # PLN-B2.1: ayni kalemin yapraklari ayni `code`u tasir — Bolumsuz once,
        # sonra bolum kimligi (deterministik sira; ekran ve anlik goruntu testleri).
        order_by="(SiteDiaryLine.code, SiteDiaryLine.section_id.nulls_first())",
    )
    worker_counts: Mapped[list["SiteDiaryWorkerCount"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="SiteDiaryWorkerCount.trade",
    )

    @property
    def is_draft(self) -> bool:
        """`Deletable` protokolü (`app/core/access.py`) için — kolon DEĞİL."""
        return self.status == DiaryStatus.draft


class SiteDiaryLine(Base):
    """Günlük poz satırı — (poz, o günkü miktar) ikilisi (spec §2).

    Poz kaynağı **BOQ**'dur (`boq_items`): tek şantiye-bazlı + fiyatlı +
    `contract_item_id` köprülü tablo, GK212 "Sözleşme BOQ'a bağlı" rozetiyle birebir.

    Kümülatif miktar (GK229) ve ₺ katkısı (GK230) TÜREVDİR — kolon açılmaz;
    ₺ hesabı KATSAYISIZ `quantity × unit_price`tır (fiyat farkı katsayısı hakediş
    katmanının işidir, günlüğün değil).
    """

    __tablename__ = "site_diary_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_site_diary_lines_quantity_nonneg"),
        CheckConstraint("unit_price >= 0", name="ck_site_diary_lines_unit_price_nonneg"),
        # Kismi benzersiz indeks (repo deseni): bagi kopmus (NULL) satirlar
        # coklanabilir, yoksa tek bir poz silindiginde tum NULL satirlar catisirdi.
        #
        # PLN-B2.1 (B2-8 / spec §2 "yaprak = kalem × bolum"): tekillik
        # (kayit, poz) → (kayit, poz, bolum). Bir UNIQUE'te NULL'lar birbirinden
        # FARKLI sayildigi icin "Bolumsuz" (section_id IS NULL) dali AYRI bir
        # kismi indeksle korunur — tek indeks (entry, poz, bolum) iki Bolumsuz
        # satiri sessizce coklardi.
        Index(
            "uq_site_diary_lines_item_section",
            "entry_id",
            "boq_item_id",
            "section_id",
            unique=True,
            postgresql_where=text("boq_item_id IS NOT NULL AND section_id IS NOT NULL"),
        ),
        Index(
            "uq_site_diary_lines_item_nosection",
            "entry_id",
            "boq_item_id",
            unique=True,
            postgresql_where=text("boq_item_id IS NOT NULL AND section_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site_diary_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL: poz silinse de o gunun kaydi snapshot'la ayakta kalir (BOQ deseni).
    boq_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("boq_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # PLN-B2.1: satirin BOLUMU (yaprak = kalem × bolum). NULL = "Bolumsuz": kalemin
    # bolume tahsis EDILMEMIS kalani (spec §3.9 B1-3) — ve eski istemcinin tek
    # yazabildigi dal (geri uyum).
    #
    # 🔴 RESTRICT (SET NULL DEGIL): SET NULL bolum silininde (poz, S1) satirini
    # (poz, NULL)a cevirir ve ayni kayittaki Bolumsuz satirla
    # `uq_site_diary_lines_item_nosection` uzerinde CAKISIRDI (IntegrityError);
    # cakismasa bile S1'de yapilan uretim sessizce "Bolumsuz"a tasinirdi.
    # CASCADE gonderilmis gunlugun miktarini silerdi. Bolum silme yolunda korkuluk
    # VAR (PLN-B2.10, CEO karari): `sites/service/deletes.py::delete_section` bolume
    # yazilmis miktar satiri varken 409 verir (`section_has_diary_lines`, eyleme donuk
    # metin); bu RESTRICT ikinci katmandir. (EV-BORC-6: eski "korkuluk YOK" notu bayatti.)
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # PLN-B2.1 (B2-8): planli miktar asildiginda gerekce. Zorunlulugu cekirdekte
    # DEGIL, Gonder portundadir (`app.core.day_hooks`, EV'li santiyede).
    overrun_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # GK228 "Bugun Yapilan". 0 mesru: BOQ iskeleti tum pozlari acar, o gun
    # dokunulmayan poz 0 kalir.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SiteDiaryWorkerCount(Base):
    """Günlük işçi kırılımı — (meslek, kaynak, adet) üçlüsü (spec §2).

    `trade` SERBEST METİNDİR (katalog yok; GK "Kalıpçı/Demirci/…"). Toplam işçi
    sayısı TÜREVDİR — kolon açılmaz.
    """

    __tablename__ = "site_diary_worker_counts"
    __table_args__ = (
        # PLN-B2.1 (B2-5): eski (meslek, kaynak) tekilligi YALNIZ firmasiz satirlarda
        # korunur (kismi indeks). Firma satiri firma basina tekildir — ayni meslek
        # iki farkli taseronda mesrudur.
        Index(
            "uq_site_diary_worker_counts_entry_trade_source",
            "entry_id",
            "trade",
            "source",
            unique=True,
            postgresql_where=text("subcontractor_id IS NULL"),
        ),
        Index(
            "uq_site_diary_worker_counts_entry_subcontractor",
            "entry_id",
            "subcontractor_id",
            unique=True,
            postgresql_where=text("subcontractor_id IS NOT NULL"),
        ),
        CheckConstraint("count >= 0", name="ck_site_diary_worker_counts_count_nonneg"),
        CheckConstraint(
            "hours IS NULL OR (hours > 0 AND hours <= 24)",
            name="ck_site_diary_worker_counts_hours_range",
        ),
        # Firma bagi yalniz taseron kaynakli satirda anlamlidir.
        CheckConstraint(
            "subcontractor_id IS NULL OR source = 'subcontractor'",
            name="ck_site_diary_worker_counts_subcontractor_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site_diary_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[WorkerSource] = mapped_column(
        Enum(WorkerSource, name="worker_source"), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    # PLN-B2.1 (B2-5): taseron FIRMA satiri — "puantaji tutulmayan firma ekibi".
    # 🔴 RESTRICT: satir o gunun firma adam-saatinin kaniti; firma silinince
    # SET NULL eski (meslek, kaynak) kismi tekilligiyle cakisabilir ve saat kimin
    # oldugunu kaybederdi. Emsal `invoicing.models` (subcontractors → RESTRICT).
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subcontractors.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Kisi basi saat (0 < h <= 24). Firma adam-saati = count × hours (turev).
    hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
