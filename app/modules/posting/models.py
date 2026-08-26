"""🔴 MU-3A — BELGE → HESAP EŞLEMESİ (`posting_rules`).

## Bu tablo NEDEN VAR

MU-3A'dan önce depoda `account_map` / `posting_rule` / `auto_post` adında
HİÇBİR ŞEY yoktu (ölçüldü, 0 eşleşme) ve `chart_of_accounts`a giden TEK yabancı
anahtar `journal_lines.account_id`ydi. Yani hesap planı ile belge dünyası
arasında hiçbir bağ yoktu: bir faturanın hangi hesaba borç, hangisine alacak
yazılacağı hiçbir yerde YAZILI DEĞİLDİ.

Alternatif, hesap kodlarını `post_document`in içine gömmekti. Reddedildi:
kodlar (`740`/`320`) ürün KARARIDIR, kod satırı değil — yönetimin KARAR-1 ve
KARAR-2'si tam olarak bu iki kodu seçer ve bir sonraki karar (MU-4, `320.04`
alt hesabı) onları DEĞİŞTİRECEKTİR. Gömülü olsalardı her karar bir kod
sürümü ister ve canlıdaki fişler ile karar arasına deploy girerdi.

## Anahtar: `(source_type, role_key)`

`role_key` fişin BACAK ROLÜDÜR — bir hesap adı değil, bir SLOT adı:
`expense`, `payable`, `vat_input`… Belge ailesi bacaklarını ROLLERİYLE
tarif eder, hesabı BİLMEZ. Böylece KARAR-2'nin geri alınması (MU-4'te
`320` → `320.04`) TEK BİR SATIR GÜNCELLEMESİDİR ve fişleme kodu hiç değişmez.

🔴 `role_key` neden bir enum DEĞİL (`source_type` enum olduğu hâlde): rol
sözlüğü aileden aileye ayrışır ve her yeni bacak bir `ALTER TYPE` isterdi.
Daha önemlisi, bir enum üyesi tek başına HİÇBİR ŞEY GARANTİ ETMEZ — üyenin
KARŞILIĞINDA BİR SATIR OLMASI gerekir. Fail-closed'ı sağlayan şey zaten odur:
`post_document` eşlemesi olmayan bir rolü çözemez ve **422** ile durur, fişi
YARIM YAZMAZ. Yazım hatası da böylece ısırır. Biçim yine de serbest değildir
(`ck_posting_rules_role_key_format`): `Expense` ile `expense` iki AYRI kural
satırı olabilseydi hangisinin çözüleceği yazım tercihi hâline gelirdi.

## `account_id`, `account_code` DEĞİL

FK `chart_of_accounts.id`ye gider ve **RESTRICT**'tir — `journal_lines.account_id`
ile AYNI desen ve aynı sebep: eşlemesi olan hesap silinemez, yoksa fişleme
sessizce çözümsüz kalır ve kusur ancak bir sonraki faturada görünürdü. Kodla
(`String`) tutulsaydı FK bir UNIQUE'e (`uq_chart_of_accounts_code`) bağlanır ve
hesabın kodu düzenlendiğinde eşleme ya kopar ya da `ON UPDATE CASCADE` ile
sessizce BAŞKA bir hesabı gösterirdi.

⚠️ Kural, gösterdiği hesabın **YAPRAK** olduğunu DB'de zorlayamaz (hiyerarşi
kodun içinde taşınır, K4). Kapı `post_document`tedir ve
`accounting.validation.leaf_blockers`ı yeniden yazmaz, ÇAĞIRIR. Bu, MU-4'ün
`320.04`ü açtığı gün `320`e bakan bir kuralın 422 vereceği anlamına gelir —
istenen budur: sessizce çift sayan bir mizan yerine gürültülü bir durma.

## KAPSAM: bu dilimde HİÇBİR ÜRÜN SATIRI TOHUMLANMAZ

MU-3A hiçbir belge ailesini bağlamaz (bağlama işi MU-3B/C/D/E'dir). Bir seed
migration'ı yazılsaydı hiçbir kodun okumadığı ÖLÜ VERİ üretirdi. Temsilî eşleme
(`740` borç / `320` alacak — KARAR-1 + KARAR-2) TESTLERDE kurulur.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.accounting.models import JOURNAL_SOURCE_TYPE, JournalSourceType

#: `role_key` dilbilgisi — küçük harf `snake_case`. `chart_of_accounts`ın kod
#: dilbilgisi CHECK'inin kardeşi: biçim DB'de durur ki iki yazım aynı slotu
#: gösteren İKİ AYRI satır üretemesin.
ROLE_KEY_PATTERN = "^[a-z][a-z0-9_]*$"

#: 40 hane: `subcontractor_retention` 24 karakterdir; en uzun makul rol adı da
#: rahatça sığar ve kolon bir serbest metin alanına DÖNÜŞMEZ.
ROLE_KEY_MAX_LENGTH = 40


class PostingRule(Base):
    """Bir belge ailesinin BİR bacak rolünün hangi hesaba düştüğü."""

    __tablename__ = "posting_rules"
    __table_args__ = (
        # 🔴 Bir rolün TEK hesabı olur. İki satır yazılabilseydi `post_document`
        # hangisini seçeceğini satır SIRASINDAN okur ve aynı fatura iki farklı
        # günde iki farklı hesaba düşebilirdi.
        UniqueConstraint("source_type", "role_key", name="uq_posting_rules_source_role"),
        CheckConstraint(
            f"role_key ~ '{ROLE_KEY_PATTERN}'", name="ck_posting_rules_role_key_format"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # 🔴 `JOURNAL_SOURCE_TYPE` — `journal_entries.source_type` ile AYNI `Enum`
    # NESNESİ (tip iki kez yaratılmasın; gerekçe `accounting/models.py`de).
    source_type: Mapped[JournalSourceType] = mapped_column(JOURNAL_SOURCE_TYPE, nullable=False)
    role_key: Mapped[str] = mapped_column(String(ROLE_KEY_MAX_LENGTH), nullable=False)
    # RESTRICT: eşlemesi olan hesap SİLİNEMEZ (`journal_lines.account_id` deseni).
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chart_of_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
