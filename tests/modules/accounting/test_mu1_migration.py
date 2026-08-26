"""MU-1 T2 — muhasebe şeması: MODEL KATMANI (enum'lar · kolonlar · FK davranışı).

Spec: `docs/superpowers/specs/2026-08-15-mu1-muhasebe-cekirdegi-design.md` §3, §4.

⚠️ Dosya 800 satır tavanını aşınca BÖLÜNDÜ (`_journal.py` emsali). Migration tur
dönüşü ve DB semantiği iddiaları `test_mu1_migration_db.py`ye taşındı; paylaşılan
yardımcılar `_mu1_migration.py`de. Hiçbir testin iddiası değişmedi.
"""

from app.modules.accounting.models import (
    ChartAccount,
    ChartAccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)

from ._mu1_migration import (
    BACKEND_DIR,
    MODEL_ENUM_LABELS,
)


def test_two_new_enums_match_spec_exactly():
    """Değerler DB'ye yazılır: sonradan düzeltmek bir enum TAKASI (migration)
    gerektirir, bu yüzden burada kilitli.

    🔑 `chart_account_type` MT-1/KK-1 ile BEŞ üyeli oldu (kullanıcı kararı):
    Bilanço `III. ÖZKAYNAKLAR` bölümü dört üyeyle ifade edilemiyordu. `equity`
    modelde vardır ama MU-1 REVİZYONUNDAKİ DB'de YOKTUR — tur dönüşü testi bu
    yüzden `EXPECTED_ENUM_LABELS`ı, bu test `MODEL_ENUM_LABELS`ı okur."""
    actual = {
        "chart_account_type": [e.value for e in ChartAccountType],
        "journal_entry_status": [e.value for e in JournalEntryStatus],
    }
    assert actual == MODEL_ENUM_LABELS


def test_account_type_has_no_invented_members():
    """🔴 K5 (MT-1'de DARALTILDI): `equity` artık bir KULLANICI KARARIDIR
    (KK-1, 2026-08-16) ve yasak listesinden çıkarıldı; gerekçesi
    `test_mt1_ozkaynak_kontra_migration.py`de. Geri kalan üyeler hâlâ
    icat edilemez — `contra` bir TÜR değil `is_contra` bayrağıdır, nazım/maliyet
    hesaplarının ise hiçbir ekranda karşılığı yoktur."""
    values = {e.value for e in ChartAccountType}
    for yasak in ("memorandum", "cost", "contra", "other", "class"):
        assert yasak not in values, yasak


def test_entry_status_has_no_invented_members():
    """K2 İKİ geçiş tanımlar; ara onay adımı (`request`/`approve`) hiçbir
    mockup'ta çizilmemiştir — `cancelled`/`deleted` de yoktur: kayıtlaştırılmış
    fiş defterden ÇIKMAZ, yalnız ters kaydıyla nötrlenir."""
    values = {e.value for e in JournalEntryStatus}
    for yasak in ("pending", "approved", "cancelled", "deleted", "closed", "locked"):
        assert yasak not in values, yasak


# --------------------------------------------------------------------------- #
# Model katmani — kolonlar
# --------------------------------------------------------------------------- #


def test_chart_account_columns_match_spec():
    """BİLEREK tam sayım: yeni bir kolon sessizce eklenemesin."""
    columns = ChartAccount.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "code",
        "name",
        "account_type",
        "is_active",
        # 🔑 MT-1/KK-1 (kullanıcı kararı, 2026-08-16): kontra bayrağı AÇILDI —
        # Bilanço `Maddi Duran Varlıklar (net)` kalemi `257`yi FİİLEN düşer.
        "is_contra",
        "created_at",
        "updated_at",
    }
    assert not columns["code"].nullable
    assert columns["code"].type.length == 20
    assert not columns["name"].nullable
    assert columns["name"].type.length == 200
    assert not columns["account_type"].nullable
    # HP:62 `Durum` — kaldırma bayrağı; varsayılan AÇIK.
    assert not columns["is_active"].nullable
    assert not columns["is_contra"].nullable


def test_chart_account_has_no_parent_or_derived_columns():
    """🔴 K4 + K3 + K-Ş2. Hiyerarşi KODUN içindedir: `parent_id` açılsaydı
    türetilebilir bir şey saklanır ve kod düzeltildiğinde FK bayatlardı.
    Bakiye SAKLANMAZ (`balance.py` TEK KAYNAK) — kolonlaşsaydı kaydığını hiçbir
    kolon farkı ele vermezdi.
    Proje/şantiye FK'sı YOKTUR: katalog ŞİRKET GENELİDİR (§3 kapsam kararı).

    🔑 `is_contra` bu listeden MT-1/KK-1 ile ÇIKARILDI (kullanıcı kararı,
    2026-08-16): türev DEĞİL, hesabın kendi niteliğidir ve sunucunun bilanço
    netlemesi ona bağlıdır. Türev alan yasağı aynen sürer."""
    columns = set(ChartAccount.__table__.columns.keys())
    for yasak in (
        "parent_id",
        "parent_code",
        "class_code",
        "level",
        "balance",
        "current_balance",
        "opening_balance",
        "project_id",
        "site_id",
        "currency",
    ):
        assert yasak not in columns, yasak


def test_journal_entry_columns_match_spec():
    """🔑 `entry_no` KUMEYE EKLENDI (FIS-NO, kullanici karari 2026-08-21).

    MU-1 kolonu "hicbir mockup sutununda fis numarasi yok" gerekcesiyle
    acmamisti; dayanak iki mockup'ta FIILEN cizili oldugu icin karar GERI
    ALINDI (`models.JournalEntry` docstring'i). Emsal MT-1/KK-1'dir: orada da
    `is_contra` bu tam sayima BOYLE eklenmisti.

    🔑 `source_type`/`source_id` KUMEYE EKLENDI (MU-3A, 2026-08-26): otomatik
    fisin idempotanligi bu ciftin uzerinde yasar (`uq_journal_entries_source` +
    `ck_journal_entries_source_pair`). Ikisi de NULLABLE'dir — elle girilen
    fiste bos kalirlar ve PG'de NULL'lar ayrik oldugu icin birbirlerini
    ENGELLEMEZLER.

    Sayim BILEREK tamdir: bu kolonlar DISINDA yeni bir kolon sessizce eklenemez.
    Kanon: kume genisledigi her seferde GEREKCE buraya yazilir, iddia
    GEVSETILMEZ.
    """
    columns = JournalEntry.__table__.columns
    assert set(columns.keys()) == {
        "id",
        "entry_no",
        "entry_date",
        "period_year",
        "period_month",
        "description",
        "detail_note",
        "status",
        "total_debit",
        "total_credit",
        "reversal_of_id",
        "source_type",
        "source_id",
        "created_by_id",
        "created_at",
        "updated_at",
    }
    assert not columns["entry_date"].nullable
    assert not columns["period_year"].nullable
    assert not columns["period_month"].nullable
    assert not columns["description"].nullable
    # E8:113 alt satırı — `invoice_lines.detail_note` ile aynı ad/rol/ölçü.
    assert columns["detail_note"].nullable
    assert columns["detail_note"].type.length == 200
    # 🔴 NOT NULL ŞART: nullable olsalardı `NULL = NULL` NULL üretir ve
    # `ck_journal_entries_posted_balanced` sessizce devre dışı kalırdı.
    for kolon in ("total_debit", "total_credit"):
        assert not columns[kolon].nullable, kolon
        assert columns[kolon].type.precision == 18
        assert columns[kolon].type.scale == 2
    assert columns["reversal_of_id"].nullable
    assert not columns["created_by_id"].nullable


def test_journal_entry_has_no_scope_columns():
    """🔑 `entry_no` YASAK KUMEDEN CIKARILDI (FIS-NO, kullanici karari).

    MU-1 bu testi "`entry_no` AÇILMAZ, `numbering.py` YOKTUR" iddiasıyla
    yazmıştı; karar geri alındı ve kolon `test_journal_entry_columns_match_spec`
    tam sayımında bekçileniyor. **İptal `entry_no` ile SINIRLIDIR** — testin
    asıl yükü olan KAPSAM (IDOR) iddiası aynen durur: proje/şantiye alanı hâlâ
    yoktur (E8:28-30 topbar'daki `Güneşkent Konut` tabloda karşılığı olmayan
    bir bağlamdır) ve `entry_number`/`document_no` gibi İKİNCİ bir numara
    kolonu da açılmaz — numara TEKTİR ve adı `entry_no`dur.
    """
    columns = set(JournalEntry.__table__.columns.keys())
    for yasak in (
        "entry_number",
        "document_no",
        "entry_type",
        "project_id",
        "site_id",
        "cost_center_id",
        "posted_at",
        "note",
    ):
        assert yasak not in columns, yasak


def test_entry_date_is_a_date_not_timestamptz():
    """🔴 K6: `entry_date` bir `date`tir. `timestamptz` olsaydı üzerinde
    `.date()` çağırmak UTC gününü verir ve TR gecesi 21:00-24:00 arasında bir
    gün geriye kayardı (`tests/test_local_calendar_guard.py` 3. kalıbı)."""
    from sqlalchemy import Date, DateTime

    entry_date_type = JournalEntry.__table__.columns["entry_date"].type
    assert isinstance(entry_date_type, Date)
    assert not isinstance(entry_date_type, DateTime)


def test_journal_line_columns_match_spec():
    """🔴 K1: `debit` ve `credit` AYRI İKİ KOLONDUR. Tek `amount` + `side`
    seçilseydi `SUM(borç)` bir `CASE` içine gizlenir ve
    `ck_journal_lines_single_side` DB'de YAZILAMAZDI."""
    columns = JournalLine.__table__.columns
    assert set(columns.keys()) == {"id", "entry_id", "sort_order", "account_id", "debit", "credit"}
    assert not columns["entry_id"].nullable
    assert not columns["account_id"].nullable
    assert not columns["sort_order"].nullable
    # `server_default` YOK: her yazma yolu sırayı açıkça doldurmalıdır
    # (varsayılan 0 olsaydı eksik doldurulan bir yol tüm satırları aynı sıraya
    # koyar ve koşan bakiye keyfî dizilirdi).
    assert columns["sort_order"].server_default is None
    # 🔴 NOT NULL: NULL tutar `SUM` tarafından YUTULUR ve dengesiz fiş dengede
    # sayılırdı.
    for kolon in ("debit", "credit"):
        assert not columns[kolon].nullable, kolon
        assert columns[kolon].type.precision == 18
        assert columns[kolon].type.scale == 2


def test_journal_line_has_no_description_or_timestamp():
    """Bir fişin iki bacağı AYNI işlemi anlatır; açıklama satıra taşınsaydı aynı
    metin tekrarlanır ve ayrışabilirdi. Satırın ömrü başlığa bağlıdır (CASCADE),
    kendi zaman damgası yoktur."""
    columns = set(JournalLine.__table__.columns.keys())
    for yasak in (
        "description",
        "detail_note",
        "note",
        "created_at",
        "updated_at",
        "amount",
        "side",
        "project_id",
        "site_id",
    ):
        assert yasak not in columns, yasak


def test_foreign_key_ondelete_behaviours():
    """CASCADE ile RESTRICT'in AYRIMI mali izin kendisidir: satır başlığın
    parçasıdır (CASCADE), hesap ise başka bir varlıktır ve satırı varken
    silinemez (RESTRICT) — CASCADE olsaydı hesabın silinmesi yevmiye satırlarını
    sessizce yok eder ve türetilmiş bakiye (K3) kaydığı fark edilmeden kayardı."""
    line_columns = JournalLine.__table__.columns
    (entry_fk,) = tuple(line_columns["entry_id"].foreign_keys)
    assert entry_fk.target_fullname == "journal_entries.id"
    assert entry_fk.ondelete == "CASCADE"

    (account_fk,) = tuple(line_columns["account_id"].foreign_keys)
    assert account_fk.target_fullname == "chart_of_accounts.id"
    assert account_fk.ondelete == "RESTRICT"

    entry_columns = JournalEntry.__table__.columns
    (reversal_fk,) = tuple(entry_columns["reversal_of_id"].foreign_keys)
    assert reversal_fk.target_fullname == "journal_entries.id"
    assert reversal_fk.ondelete == "RESTRICT"

    (user_fk,) = tuple(entry_columns["created_by_id"].foreign_keys)
    assert user_fk.target_fullname == "users.id"
    assert user_fk.ondelete == "RESTRICT"


def test_module_does_not_import_other_modules():
    """P10'un `cost_cards` import çemberi tekrarlanmaz: FK hedefleri STRING
    tablo adıyla verilir, `app.modules.users` import EDİLMEZ."""
    source = (BACKEND_DIR / "app" / "modules" / "accounting" / "models.py").read_text()
    assert "from app.modules." not in source
    assert "import app.modules." not in source


# --------------------------------------------------------------------------- #
# Migration tur donusu
# --------------------------------------------------------------------------- #
