# İK-3 — Bordro Çekirdeği (backend) · TASARIM

Tarih: 2026-08-13 · Repo: backend · Yönetim oturumu yazdı (⚡ düzen, WORKFLOW §2)
Mockup otoritesi: `projedesign/Bordro Yönetimi.dc.html` (BY) · `Bordro Geçmişi.dc.html` (BG) ·
`SGK Bildirimi.dc.html` (SGK)

---

## 1. Kapsam

**İÇERİDE:** bordro dönemi (ay) · dönem satırları (personel başına brüt/kesinti/net) ·
yapılandırılabilir oran tablosu · puantajdan gün+brüt türetme · banka/elden bölüşümü ·
satır ve toplu ödeme onayı · dönem geçmişi özeti (BG) · SGK prim hesap özeti (SGK) · Excel export.

**DIŞARIDA (basılmaz, uç açılmaz):**
- **EFT talimatı gönderme** (BY 319) — banka entegrasyonu yok.
- **Makbuz oluşturma** (BY 328) — belge modülü form-slot borcu (BC dilimi).
- **SGK'ya gerçek gönderim** (SGK 44) — dış sistem entegrasyonu yok; yalnız hesap + "gönderildi"
  damgası (elle işaretleme) modellenir.
- Çok aşamalı onay motoru · otomatik devreden-devir job (İK-3'ün ertelenen kalan parçaları).

---

## 2. Kullanıcı kararları (2026-08-13, PARA sınıfı — yeniden tartışılmaz)

| # | Karar | Sonucu |
|---|---|---|
| **K1** | **Kesinti = yapılandırılabilir oran tablosu** | Oranlar veriden okunur, koda gömülmez. Mevzuat değişince kod değişmez. Dilimli/kümülatif gelir vergisi motoru YOK. |
| **K2** | **Taşeron işçisi = yalnız bilgi/maliyet görünümü** | Taşeron satırları görünür ve maliyete girer, **ödeme onayına GİRMEZ**. Ödemesi hakediş üzerinden taşerona yapılır (TH modülü). Çift ödeme **yapısal olarak imkânsız** olmalı. |
| **K3** | **Brüt = puantajdan otomatik + elle düzeltilebilir** | Sistem gün × ücretten hesaplar; kullanıcı üzerine yazabilir (mesai/ikramiye/avans). Düzeltme **iz bırakır** (kim/ne zaman/önceki değer). |

---

## 3. Yönetimin bağladığı kararlar (mockup + kayıtlı kanon)

**S1 · Mockup'lar arası çelişki → açık oran kazanır.** BY tablosundaki şirket satırları %29,81
kesinti gösteriyor (37.800→11.262 · 50.600→15.086), SGK 60-75 ise oranları AÇIKÇA yazıyor:
SGK işçi **%14** · işsizlik işçi **%1** · gelir vergisi stopajı **%10** · damga **%0,759**
(toplam %25,759) · SGK işveren **%20,5** · işsizlik işveren **%2** · kısa çalışma **%1**.
İkisi aynı anda doğru olamaz. **Açıkça yazılı oranlar SEED değeri olur** (mevzuata da uygun);
BY'deki tutarlar temsilî kabul edilir. Gerekçe: K1 zaten hesabı orandan türetiyor, tutar türevdir.

**S2 · Oran seti personel TİPİ bazındadır.** BY bölüm başlıkları dört ayrı rejim çiziyor:
şirket kadrosu "SGK 4a" (BY 127) · taşeron "SGK Taşeron" (BY 175) · serbest meslek
"Serbest Makbuz · **%20 stopaj**" (BY 243, veri de doğruluyor: 12.500→2.500) · stajyer
"Staj ücreti", kesinti sütunu **"—"** (BY 284, kesinti YOK). Oran tablosu bu yüzden
`(yıl, personel_tipi)` anahtarlıdır, tek global oran değildir.

**S3 · `banka + elden = net` KESİN İNVARİANTTIR.** BY verisiyle doğrulandı (10.000+9.336=19.336 ·
0+16.080=16.080 · 26.538+0=26.538). Sunucu bunu **doğrular, ihlal 422**; istemci hesabına
güvenilmez. Kuruş hassasiyeti `Numeric(12,2)`.

**S4 · Ücreti olmayan personelde brüt HESAPLANMAZ — 0 BASILMAZ** (SA dilimindeki NULL-EŞİK
kanonu, WORKFLOW §4). `wage_amount`/`wage_type` NULL ise satır **"hesaplanamadı"** durumunda açılır,
brüt/net **`null`** döner ve **ödeme onayına GİRMEZ** (fail-closed). Uydurma 0, eksik veriyi
"ödenecek bir şey yok" gibi gösterir — para sınıfı yalan.

**S4.1 · PUANTAJ KAYDI olmayan personelde de brüt HESAPLANMAZ — yönetim kararı,
2026-08-13 (T4b).** Dönemde personele ait HİÇ `timesheet_entries` kaydı yoksa
"bu ay hiç çalışmadı" ile "puantaj henüz girilmedi" AYIRT EDİLEMEZ → satır
**`uncomputed`**, para alanları `null`, gün `null`. **`daily` · `hourly` ·
`monthly` — üçünde de** (aylıkçıda sessiz tam maaş, işe hiç başlamamış kişiye
maaş hesaplardı). ⚠️ Kayıt VAR ama hepsi `MAN_DAY_CODES` dışıysa (izin/tatil)
gün 0 **GERÇEKTİR** → normal hesap (`pending`). Çıkış yolu K3 override'ıdır
(`uncomputed → pending`); kural bordroyu TIKAMAZ.

**S5 · Onaylanan satır DEĞİŞTİRİLEMEZ.** `approved`/`paid` satırda brüt/kesinti/bölüşüm PATCH'i
**409**. Gerekçe: ödeme izi. Düzeltme yolu satırı `pending`e geri alma yetkisidir (ayrı izin),
dönem `paid` ise o da kapalıdır.

**S6 · Dönem+personel için TEK satır** (UQ `(payroll_period_id, personnel_id)`). Dönem yeniden
hesaplanırsa mevcut satırlar **güncellenir**, elle düzeltilmiş (`is_overridden`) satırlar
**KORUNUR** — yeniden hesap kullanıcının düzeltmesini sessizce ezemez (K3'ün gereği).

**S7 · Gün sayısı puantajdan okunur** (`timesheet`, PT dilimi `MAN_DAY_CODES` kanonu).
Serbest meslekte gün **yoktur** (BY 254 "—") → `days` `null`, brüt elle girilir.

**S8 · İzin verilen durum geçişleri** (BY 56/303 + BG durum sütunu):
dönem `draft → pending_approval → approved → paid`; satır `pending → approved → paid`.
Geri geçiş yalnız `pending`e ve yalnız dönem `paid` DEĞİLKEN. Atlama YOK.

**S9 · İzin modülü `payroll` — ⚠️ DÜZELTİLDİ 2026-08-13 (ilk yazımda HATALIYDI).** Spec önce
"21. modül açılır" diyordu; **yanlış**: `payroll` modülü **ilk seed'den beri var**
(`alembic/versions/a477fdf00fdf_seed_roller_modul_ve_izinler.py:88`). İK-3 şefi tespit etti,
yönetim doğruladı. **Yeni izin modülü AÇILMAZ**, mevcut `payroll` kullanılır (ST/`inventory`
emsalinin aynısı). `full` = hesapla/düzelt/onayla, `read` = görüntüle; ayrı `payroll:admin`
AÇILMAZ (silme ucu yok).

**S10 · `WorkerSource` enum'u dört tipe genişler (yönetim ONAYI, 2026-08-13).** Oran tablosu dört
personel tipi ister (S2) ama `worker_source` DB tipi yalnız `company`/`subcontractor`/`general`
taşıyordu; İK-1 bu takası açıkça İK-3'e ertelemişti (`personnel/models.py:95`). Karar: **mevcut
paylaşılan enum'a `freelance` + `intern` EKLENİR**, paralel ikinci bir tip AÇILMAZ (aynı anlam
kümesinin iki DB tipi olması daha kötü). `general` bordro tipi DEĞİLDİR (oran satırı yoktur).
**İki korkuluk zorunlu:** (a) enum değeri Postgres'te DROP edilemediği için downgrade tipi yeniden
yaratmalı ve migration turu **veri varken** koşulmalı; (b) enum `site_diary` · `timesheet` ·
`personnel` yüzeylerinde de paylaşıldığı için sızma etkisi (eksik etiket/rozet/export sütunu)
**frontend devir notu** olarak raporlanır — bu dilimde kod değiştirilmez.

---

## 4. Veri modeli

**`payroll_periods`** — `id` · `year` · `month` · `status` (enum `payroll_period_status`:
draft/pending_approval/approved/paid) · `payment_due_date` (BY 63 "Son ödeme") · `approved_by_id`
· `approved_at` · `paid_at` · `sgk_submitted_at` (SGK damgası, elle) · audit sütunları.
UQ `(year, month)` — bir ay için tek bordro.

**`payroll_lines`** — `id` · `payroll_period_id` (CASCADE) · `personnel_id` (RESTRICT — bordro
satırı olan personel silinemez, para izi) · `personnel_source` (satır anındaki tip **snapshot**'ı;
personelin tipi sonradan değişse geçmiş bordro değişmez) · `days` (nullable, S7) · `gross_amount`
(nullable, S4) · `deduction_amount` (nullable) · `net_amount` (nullable) · `bank_amount` ·
`cash_amount` · `is_overridden` (K3) · `overridden_by_id` · `overridden_at` ·
`previous_gross_amount` (K3 izi) · `status` (enum `payroll_line_status`:
uncomputed/pending/approved/paid/excluded) · `excluded_reason` (K2 taşeron için).
UQ `(payroll_period_id, personnel_id)` (S6).

**`payroll_rates`** — `id` · `year` · `personnel_source` · yedi oran sütunu
(`sgk_employee_pct` · `unemployment_employee_pct` · `income_tax_pct` · `stamp_tax_pct` ·
`sgk_employer_pct` · `unemployment_employer_pct` · `short_work_pct`) · `is_active`.
UQ `(year, personnel_source)`. **SEED:** 2026 yılı için dört tip — oranlar S1'den; serbest meslek
yalnız `income_tax_pct = 20` (S2, BY 243), stajyer **tüm oranlar 0** (BY 284).

---

## 5. Uçlar

| Uç | Not |
|---|---|
| `GET /payroll/periods` | BG listesi: dönem + çalışan sayısı + brüt/SGK işveren/net/toplam maliyet + ödeme tarihi + durum. Sayfalama TB3 deseni (`limit` varsayılan 50, `le=200` → aşım **422**). |
| `POST /payroll/periods` | Ay aç (`year`+`month`). Var olan ay → **409**. `payment_due_date` **opsiyonel** (T4b). |
| `PATCH /payroll/periods/{id}` | **T4b** — yalnız `payment_due_date`. `draft`/`pending_approval` yazılabilir; `approved`/`paid` → **409**. Sunucu tarih ÜRETMEZ/DENETLEMEZ; boş gövde **422**. |
| `GET /payroll/periods/{id}` | Dönem + 4 özet kartı (BY 69-93) + tip bazında gruplanmış satırlar. |
| `POST /payroll/periods/{id}/compute` | Puantaj+ücret+oranlardan satırları üret/güncelle. `is_overridden` satırları KORUR (S6). Dönem `approved`/`paid` ise **409**. |
| `PATCH /payroll/lines/{id}` | Brüt override (K3) + banka/elden bölüşümü (S3). `approved`/`paid` satırda **409** (S5). |
| `POST /payroll/lines/{id}/approve` · `/reject` | Satır onayı. **Taşeron satırı → 409** (K2). |
| `POST /payroll/periods/{id}/approve` | "Tümünü Onayla" (BY 303). Yalnız `pending` satırları onaylar; `uncomputed` ve taşeron satırları **atlanır** ve yanıtta **atlananlar sayısıyla raporlanır** (sessiz atlama yok, WORKFLOW §3). |
| `POST /payroll/periods/{id}/pay` | Ödendi damgası (`paid_at`). |
| `GET /payroll/periods/{id}/sgk-summary` | SGK 55-95 prim hesabı: işçi payları + işveren payları + toplam prim. |
| `POST /payroll/periods/{id}/sgk-submit` | Yalnız `sgk_submitted_at` damgası (dış entegrasyon YOK). |
| `GET /payroll/rates` · `PUT /payroll/rates/{year}/{source}` | Oran tablosu yönetimi (K1). |
| `GET /payroll/periods/{id}/export` | Excel (BY 55; puantaj export emsali). |

---

## 6. Zorunlu korkuluklar (test edilecek)

1. **S3 invariantı:** `bank + cash ≠ net` → **422** (kuruş kaymasında da).
2. **K2 çift ödeme:** taşeron satırı hiçbir yoldan `approved` olamaz — satır onayı 409, toplu onay atlar,
   `net` toplamı ödeme kartlarına girmez. **Mutasyonla kanıtlanır.**
3. **S4 fail-closed:** ücretsiz personelde brüt `null`, satır `uncomputed`, onaya girmez (0 DEĞİL).
4. **S5 değişmezlik:** `approved` satırda PATCH → 409.
5. **🔴 EŞİK = KİLİT (WORKFLOW §4, İK-2 dersi):** dönem/satır onayı ve `compute` **`FOR UPDATE`**
   altında; serileştirme **dönem satırında**, kilit denetimlerden ÖNCE, sıra sabit dönem→satır.
   Regresyon **iki gerçek bağlantıyla**: eşzamanlı iki `approve` çift onay/çift toplam üretmemeli;
   kilit kaldırılınca test KIRMIZI olmalı.
6. **S6 yeniden hesap:** `compute` iki kez koşunca `is_overridden` satır DEĞİŞMEZ, diğerleri tazelenir.
7. **S8 geçiş:** atlama (`draft → approved`) → 409.
8. Görünmeyen kayıt → **404** (var olmayanla ayırt edilemez).

---

## 7. Bilinçli sınırlar (eksik değil — geri açılmaz)

- **Toplam maliyet = brüt + İŞVEREN PRİMLERİNİN TAMAMI** — ⚠️ **NETLEŞTİRİLDİ 2026-08-13.** İlk
  yazımda "brüt + SGK işveren payı" deniyordu; **eksikti.** İşveren tarafı SGK 78-86'da ÜÇ kalemdir
  (SGK işveren `%20,5` · işsizlik işveren `%2` · kısa çalışma `%1`) ve üçünün de oran sütunu vardır
  (§4) — biri toplama girmezse işveren maliyeti eksik çıkar (para sınıfı hata). Formül:
  `toplam_maliyet = brüt + (sgk_employer + unemployment_employer + short_work)`.
  **Mockup toplamları bunu doğrulamaz ve doğrulaması BEKLENMEZ:** SGK 82 işveren toplamını 148.800
  yazıyor ama kendi oranlarından 174.652 çıkıyor; BG 892.000'i de 148.800'e dayanıyor. **S1 gereği
  açık ORAN kazanır, tutarlar temsilîdir** — mockup toplamları test beklentisi DEĞİLDİR.
  Kıdem/ihbar karşılığı, yemek/yol yardımı DAHİL DEĞİL — mockup çizmiyor.
- **Kümülatif gelir vergisi matrahı takip EDİLMEZ** (K1: düz oran). Yıl içinde dilim atlaması
  modellenmez; oran tablosu yıllıktır.
- **Asgari ücret istisnası / AGİ yok** — mockup çizmiyor, K1 kapsamı dışı.
- **Avans/icra kesintisi yok** — brüt override'ı (K3) bu ihtiyacı karşılar.
