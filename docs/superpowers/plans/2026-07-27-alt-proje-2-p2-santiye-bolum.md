# Alt-Proje 2 · P2 — Şantiye & Bölüm (backend uygulama planı)

Tarih: 2026-07-27
Bağlı spec: `docs/superpowers/specs/2026-07-27-alt-proje-2-p2-santiye-bolum-design.md`
Yürütme: `superpowers:subagent-driven-development` — task-by-task, her task bağımsız review'lı
Dal: `feat/p2-santiye-bolum` (P1 head `6fc91c2` üzerine)

## Kurallar (her task için geçerli)

- **TDD zorunlu:** kırmızı → yeşil → refactor. Test yazılmadan implementasyon yok.
- **Test DB:** `backend/.env`'deki `TEST_DATABASE_URL` **UZAK Railway host'udur** ve
  conftest `drop_all` yapar. Testler ASLA oraya koşturulmaz. Lokal
  `brew postgresql@18` (5432) üzerinde tek kullanımlık DB açılır, env ile
  yönlendirilir, task bitince düşürülür.
- **PATH'te python yok:** `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/alembic`,
  `.venv/bin/ruff`. Global ruff (0.8.6) yanlış pozitif verir — pyproject `ruff==0.15.22`.
- **Ajanlar push etmez.** Merge/push/deploy kararı kullanıcıdadır.
- Her task sonunda `ruff check` + `ruff format --check` + tam `pytest` yeşil olmalı.

---

## Task 1 — `sites` ve `sections` modelleri + enum'lar

**Dosya:** `app/modules/sites/__init__.py`, `app/modules/sites/models.py`

Spec §2.1–2.3. `SiteStatus`, `SectionStatus` enum'ları; `Site`, `Section` modelleri;
`Site.sections` relationship (`lazy="selectin"`, `cascade="all, delete-orphan"`,
`order_by="Section.sort_order"`); `Project.sites` ters relationship.

**Testler (önce):**
- `uq_sites_project_code` — aynı projede aynı kod IntegrityError; farklı projede geçerli
- `sections.code` NULL çoklu satır geçerli (kısmi indeks)
- Proje silinince şantiye, şantiye silinince bölüm cascade düşer
- `section_status` varsayılanı `planned`, `site_status` varsayılanı `active`

**Bitti tanımı:** modeller `Base.metadata`'da; testler yeşil.

---

## Task 2 — Migration `p2_santiye_bolum`

**Dosya:** `alembic/versions/<hash>_p2_santiye_bolum.py`

Spec §6. `down_revision = "b7fcd67bde1e"`. İki enum, iki tablo, indeksler,
`modules` satırı, 8 `role_permissions` satırı. `downgrade()` tam tersi.

`sort_order: 4`'ün `modules` tablosunda boş olduğu migration içinde doğrulanır;
doluysa sonraki modüller kaydırılır.

**Testler:** `alembic upgrade head` → `downgrade -1` → `upgrade head` lokal
Postgres'te temiz koşar; `sites` modülü 16. satır olarak gelir.

**Bitti tanımı:** tek head; up→down→up yeşil.

---

## Task 3 — İzin modülü seed'i ve modül sayısı güncellemesi

**Dosya:** `app/modules/roles/seed_data.py`, ilgili testler

Spec §5.1. `MODULES` listesine `sites`; rol matrisine `sites` satırı.
`roles` testlerindeki sabit **15 → 16**.

> ⚠️ İzin profili (§5.1 tablosu) kullanıcı onayı bekliyor — açık soru 1.
> Onay gelmemişse spec'teki öneri uygulanır ve task notunda işaretlenir.

**Testler:** modül sayısı 16; `sites` her rolde beklenen seviyede; Sistem
Yöneticisi satırı değiştirilemez (mevcut kilitlenme koruması testi kapsar).

---

## Task 4 — Şemalar

**Dosya:** `app/modules/sites/schemas.py`

Spec §4.1. `SiteCard`, `SiteDetailResponse`, `SiteListResponse` (`counts` +
`items` + `totals`), `SectionResponse`, `SectionListResponse`, `SiteCreate`,
`SiteUpdate`, `SectionCreate`, `SectionUpdate`.

`MetricPlaceholder` / `CountPlaceholder` **`app/modules/projects/schemas.py`'den
import edilir**, kopyalanmaz. Ortak yere taşımak gerekirse `app/core/schemas.py`
açılır ve `projects` da oradan alır (tek hamlede, DRY).

**Testler:** şema serileştirme; yer tutucu alanlar her zaman `available: false`
ve doğru `pending_module`.

---

## Task 5 — Repository katmanı

**Dosya:** `app/modules/sites/repository.py`

Proje bazlı şantiye listesi, id ile şantiye + bölümler, bölüm listesi, bölümden
şantiye/proje çözümü (yetki için), durum sayaçları.

**Testler:** sayaçlar doğru; bölümsüz şantiye boş liste; sıralama `sort_order`.

---

## Task 6 — Servis katmanı

**Dosya:** `app/modules/sites/service.py`

Spec §3, §4.2, §4.3, §5.2. Kart üretimi, `remaining_days`, `city_inherited`,
`section_status_counts`, yer tutucu doldurma. Görünürlük süzgeci **P1'in
`_visible_projects`'ünden** gelir — kopya mantık yazılmaz; gerekirse P1 servisinde
yeniden kullanılabilir bir yardımcıya çıkarılır.

**Testler:** spec §7 "Servis" başlığındaki tüm maddeler.

---

## Task 7 — Router + denetim günlüğü

**Dosya:** `app/modules/sites/router.py`, `app/modules/audit/messages.py`, `app/main.py`

Spec §4 tablosundaki 7 uç; `require_permission("sites", …)`; create/update
uçlarında `record_audit` (B5 deseni, yeni Türkçe mesajlar).

**Testler:** her uç mutlu yol; denetim satırı yazılıyor.

---

## Task 8 — Yetki negatif testleri (ayrı task, atlanamaz)

**Dosya:** `tests/modules/sites/test_sites_permissions.py`

Spec §7 "Yetki — negatif testler" başlığının tamamı. Özellikle
`PATCH /sections/{id}` üzerinden dolaylı erişim → 404.

Ayrı task olmasının sebebi: aynı task içinde yazıldığında implementasyonu yazan
ajan testleri kendi kodunun şekline uydurma eğilimindedir.

---

## Task 9 — `GET /projects/{id}` şantiye sayacı

**Dosya:** `app/modules/projects/service.py`, `schemas.py`

Proje detayına `site_count` eklenir (gerçek değer, yer tutucu değil). P1
sözleşmesine **eklemedir**, kırıcı değişiklik değil.

**Testler:** şantiyesiz proje `0`; iki şantiyeli proje `2`.

---

## Task 10 — OpenAPI üretimi + frontend'e aktarım

Backend README'deki akış: şema üret → `../frontend/openapi/` → frontend'de
`pnpm gen:api`. Bu task **frontend deposunda dosya değiştirir** — backend ajanı
yalnız `openapi.json`'ı üretip kopyalar; `gen:api` frontend planının ilk task'ıdır.

---

## Task 11 — Kod incelemesi ve kapanış

`fastapi-reviewer` + `security-reviewer` (yetki/görünürlük dokunulduğu için
zorunlu). CRITICAL/HIGH bulgular düzeltilir. Kapsam ≥ %80 doğrulanır.

Sonra: bellek notu güncellenir, kullanıcıya merge/push/deploy sorulur.

---

## Sıralama ve paralellik

Sıra: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 (doğrusal; her task
öncekinin çıktısına dayanıyor).

**Frontend paralel yürüyebilir** ancak Task 10'a kadar gerçek sözleşme yoktur;
frontend planı bu yüzden sahte backend sözleşmesiyle (spec §4.1 JSON'ları)
başlar ve Task 10 sonrası üretilen tiplere geçer. Aynı repoda aynı anda iki ajan
çalıştırılmaz.
