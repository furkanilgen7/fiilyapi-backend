# P8 — Ünite Satışı (backend spec)

Tarih: 2026-08-02 · Durum: **ONAYLANDI (2026-08-02)** — §8'in TÜM soruları önerildiği gibi onaylandı:
S1 yeni `sales` izin modülü (matris 18→19) · S2 taksit üstü manuel tahsilat + `pay` ucu BU dilimde ·
S3 `landowner` üniteler satışa kapalı · S4 rezervasyonda otomatik iptal yok · S5 gecikme faizi yalnız
gösterim türevi · S6 "Fiyat Listesi" kapsam dışı.
**ONAYLI SAPMA (2026-08-02, kapanışta):** Vade farkı (F106) plan tutarlarını ŞİŞİRMEZ — oran bilgi
alanı olarak saklanır, "plan toplamı = sale_price" kuralı korunur (mockup'taki tek örnekte oran 0 ve
TOPLAM = satış bedeli). Vade farkının tutara yansıma iş kuralı netleşirse ayrı dilimde `sales/plan.py`
üzerinde ele alınır.
Mockup'lar: `projedesign/Form - Daire Satisi.dc.html` (F) · `projedesign/Satış Yönetimi.dc.html` (S)
Mevcut zemin: `units` tablosu satışa hazır (`list_price`, `min_sale_price`, `vat_rate`, `sales_status`,
`owner_side`, `appraisal_value`, m² alanları) · `units/models.py:232-240` bu dilimi açıkça tarifliyor:
satış kaydıyla `sales_status` OTOMATİKLEŞİR ve elle giriş KİLİTLENİR.

## 1. Kapsam
Alıcı (müşteri) kaydı + ünite satış kaydı + taksitli ödeme planı + tapu/teslim takibi + Satış Yönetimi
ekranının KPI/doluluk/liste uçları. Satış belgeleri ve fatura kesimi bu dilimde YOK (aşağıda).

## 2. Yeni tablolar
### `customers` (alıcı — işverenden AYRI tablo; F70-76)
`id` · `customer_type` enum(`person`,`company`) (F70) · `name` String(200) NOT NULL (F71) ·
`national_id` String(11) nullable (TCKN) + `tax_number` String(11) nullable (VKN) — tip başına biri dolu (F72) ·
`phone` String(20) (F73) · `email` String(254) (F74) · `address` Text (F76) · created/updated_at.
Benzersizlik: TCKN ve VKN ayrı kısmi unique index.

### `unit_sales` (satış kaydı — ünite başına en çok BİR açık kayıt)
`id` · `unit_id` FK→units **RESTRICT** · `project_id` FK→projects CASCADE (görünürlük süzgeci için) ·
`customer_id` FK→customers RESTRICT · `sale_type` enum(`sale`,`reservation`,`pre_contract`) (F56) ·
`status` enum `unit_sale_status`: `reservation` → `active` (sözleşmeli/taksitli) → `deed_transferred`
(Tapu Devredildi, S166) + `cancelled` · `list_price_snapshot` · `discount_amount` (F85) ·
`sale_price` NOT NULL (F86) · `vat_pct` (F87, küme {1,10,20}) · `advisor_user_id` FK→users SET NULL +
`advisor_name` snapshot (F75) · `reservation_deposit` + `reservation_due_date` (S188 "kapora · 15 gün") ·
tapu/teslim: `deed_condition` enum(`full_payment`,`after_down_payment`,`at_contract`) (F156) ·
`planned_deed_date` (F157) · `delivery_date` (F158) · `has_condominium_easement` bool (F161) ·
`has_mortgage` bool (F162) · `late_fee_monthly_pct` Numeric(5,2) nullable (F163; dolu=uygulanır) ·
`payment_plan_type` enum(`cash`,`down_payment_installments`,`bank_loan`,`barter`) (F99) ·
`down_payment` (F103) · `installment_count` (F104) · `first_installment_date` (F105) ·
`term_interest_pct` (F106) · `created_by` FK→users RESTRICT · satış taslağı YOK (kayıt ya rezervasyon
ya satıştır) · aynı ünitede ikinci AÇIK kayıt (cancelled hariç) kısmi unique index ile engellenir.

### `sale_installments` (taksit planı; F110-147)
`id` · `sale_id` FK→unit_sales CASCADE · `sequence_no` (0=peşinat) · `label` (F118 "Peşinat"/"1 / 12") ·
`due_date` · `amount` Numeric(18,2) · `payment_method` enum(`transfer`,`cash`,`cheque`,`auto_payment`) (F122/129) ·
**tahsilat (§8 S2):** `paid_amount` Numeric(18,2) default 0 + `paid_at` nullable · UQ (sale_id, sequence_no).
Plan toplamı = `sale_price` (server doğrular); "Gecikmiş" = türev (due_date geçmiş + paid_amount < amount).

## 3. `units.sales_status` otomasyonu (P3.1 karar 4'ün tamamlanması)
- Satış kaydı `reservation` → ünite `reserved`; `active` → `sold`; `deed_transferred` → `sold` kalır
  (S haritası "Tapulu"yu satış kaydının durumundan okur); `cancelled` → `listed`e döner.
- **Elle `sales_status` girişi KİLİTLENİR** (PATCH /units gövdesinden çıkar) — mevcut UI olmadığından kırıcı değil.
- `owner_side='landowner'` üniteler satışa KAPALI (§8 S3) — 422.

## 4. Uçlar (izin modülü → §8 S1)
- `GET/POST /customers` + `GET/PATCH /customers/{id}` (silme YOK — satış bağlı olabilir)
- `GET /projects/{id}/sales` (liste: S150-212 kolonları — tahsil edilen/kalan türev) ·
  `POST /projects/{id}/sales` · `GET/PATCH /sales/{id}` · `DELETE /sales/{id}` yalnız `reservation` +
  admin/`can_delete` deseni (`active`/`deed_transferred` silinmez, iptal edilir)
- `POST /sales/{id}/generate-plan` (peşinat+taksit+vade farkından satırları üretir — server otoritesi) ·
  `PUT /sales/{id}/installments` (**DEĞİŞTİRME semantiği**, hakediş lines deseni) ·
  `POST /sales/installments/{id}/pay` (tahsilat işle; §8 S2)
- Geçişler: `POST /sales/{id}/activate` (rezervasyon→satış) · `/transfer-deed` · `/cancel` (gerekçeli)
- `GET /projects/{id}/sales/summary` (S55-59 KPI'ları + S218-234 yaklaşan tahsilatlar) ·
  doluluk haritası mevcut `units` uçlarından (`sales_status` + blok gruplaması) — yeni uç gerekmez.
- Audit: tüm yazma uçları; `AuditAction` + `messages.py` genişler.

## 5. Bilinçli sınırlar (kalıcı kararlarla uyum)
- **Maliyet/kâr YOK** (karar 3): F62 "Maliyet", F90 "Bu Satıştan Kâr", S kâr alanları → `pending_module: "project_costs"` (P10).
- **`min_sale_price` altına satış zorlanmaz** (karar 2) — uyarı da eklenmez.
- **Satış belgeleri** (F168-202, 6 alan) → belge çekirdeği (karar 8) — tablo/alan açılmaz.
- **"Peşinat için otomatik fatura" (F206)** → `invoicing` kodu yok — basılmaz, `pending_module: "invoicing"`.
- **Tahsilat hazine bağı** → taksit üstü manuel kayıt (§8 S2); hazine entegrasyonu kendi diliminde.
- İleri bağ kuralı korunur: `units`'a `sale_id` kolonu AÇILMAZ (ilişki `unit_sales.unit_id` yönünden).

## 6. Görünürlük / IDOR
Tüm satış uçları `visible_projects` süzgecinden geçer; görünmeyen kayıt → 404. `customers` proje-bağımsız
(şirket geneli) — erişim izin modülü seviyesinde (§8 S1).

## 7. Migration
Tek zincir, ebeveyn **main HEAD'i** (TB1 merge'liyse onunki; P6 dalı BEKLENMEZ — çakışan tablo yok).
3 yeni tablo + 4+ yeni enum; downgrade'de `DROP TYPE` unutulmaz.

## 8. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — İzin modülü:** yeni **`sales`** modülü açılsın mı (matris 18→19; satış yetkisi proje yetkisinden
  ayrılır)? Alternatif: `projects` üzerinden (units gibi). Önerim: **yeni `sales` modülü**
  (seed+migration+matris testi birlikte).
- **S2 — Tahsilat:** taksit üzerine manuel ödeme kaydı (`paid_amount/paid_at` + `pay` ucu) bu dilimde mi?
  Önerim: **evet** — S ekranının Tahsil/Kalan/Gecikmiş kolonları bunsuz çalışmaz; hazine bağı ileride.
- **S3 — Arsa sahibi üniteleri:** `owner_side='landowner'` satışa kapalı mı? Önerim: **kapalı**
  (hissedar-ünite dağılımı P9'un işi; P9 sonrası yeniden değerlendirilir).
- **S4 — Rezervasyon süresi:** dolunca otomatik iptal YOK — manuel iptal + ekranda "süresi doldu" türevi.
  Onay? Önerim: evet (zamanlanmış iş altyapısı yok).
- **S5 — Gecikme faizi:** yalnız GÖSTERİM türevi (S223 ₺4.200; tahakkuk/borç kaydı yok). Onay? Önerim: evet.
- **S6 — "Fiyat Listesi" butonu (S24):** ekran mockup'ı yok → kapsam DIŞI; istersen mockup ver, ayrı ele
  alalım. Önerim: kapsam dışı.
