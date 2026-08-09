# TB4 — Borç Paketi (backend spec)

Tarih: 2026-08-09 · Durum: **ONAYLANDI (2026-08-09)** — §5'in ÜÇ sorusu da önerildiği gibi onaylandı:
S1 birebir eşitlik → `diary`, kısmi/yaklaşık `manual`, taslak sayılmaz · S2 senkron tazeleme ·
S3 yalnız sınırsız alanlara 2000 (migration'sız).
Kaynak: `ROADMAP-BACKEND.md` §3 borç tablosu + `GOREV-SIRASI.md` §2 (satır 182, P5 devri).
Mockup YOK — bu bir borç/temizlik dilimidir; davranış kaynakları mevcut kayıtlı kararlardır.

## 1. Kapsam (4 borç; öncelik sırasıyla)

### B1 — SD-2: sunucu-tarafı `quantity_source=diary` damgası (kullanıcı kararı 2026-08-03)
Yöntem ROADMAP §3'te KARARLI: damga İSTEMCİDEN ALINMAZ (sahte doldurulabilirdi). `PUT lines`
(işveren + taşeron İKİ aile) gelen satır miktarını, hakedişin DÖNEMİNE ait şantiye günlüğü
toplamıyla (yalnız `submitted` günlükler; köprü: satırın bağlı olduğu poz/kalem) karşılaştırır:
**birebir eşitse** satıra `diary`, değilse `manual` basılır. Damga her PUT'ta YENİDEN türetilir
(eski damga korunmaz — miktar değiştiyse kaynak iddiası da düşer). Taslak günlük TOPLAMA GİRMEZ
(SD kararı: "taslak günler tabloya girmez" emsali).

### B2 — P5 devri: dağıtım "kalan" hesabı ÇİFT TANIM
Aşım kontrolü ile "kalan" göstergesi FARKLI kümeden topluyor (GOREV-SIRASI 182/1). Bugün ayrışma
doğurmuyor ama iki doğruluk tanımı kodda. Çözüm: tek kaynak fonksiyona indirilir — **aşım
kontrolünün kümesi kazanır** (kota/guard tanımı otoritedir; gösterge ona uyar). Davranış
değişikliği BEKLENMEZ; ayrışmayı üretmeye çalışan test yazılır (mutasyonla kanıt).

### B3 — P5 devri: işveren kalemi değişince dağıtılmış BOQ satırı tazelenmiyor
`unit_price`/`code` değişince dağıtım ekranı doğru, **BOQ ekranı eski değeri gösteriyor**
(GOREV-SIRASI 182/2; hakediş tarafı SD'de kapandı, BOQ tarafı sürüyor). §5 S2'ye bağlı çözüm
önerisi: işveren kalemi PATCH'inde dağıtılmış (ayna) BOQ satırlarının fiyat/kod alanları
SENKRON tazelenir — dağıtım zaten ayna satır üretiyor (F-P5 canlı smoke'unda gözlendi), bayat
kopya bir snapshot kararı değil unutulmuş senkron. Tazeleme yalnız AYNA alanları (miktarlara
DOKUNULMAZ), audit mevcut update olayının detayına işlenir, yeni `AuditAction` YOK.

### B4 — Küçük temizlikler (karar gerektirmeyen + S3)
- `tests/progress_payments/test_concurrency.py:106-107` seed **commit** sızıntısı → fixture
  commit'siz düzenlenir (TB1'de fiilen ısırmıştı; alfabetik koşu sırası şansına dayanıyor).
- (§5 S3) `description`/serbest metin tavan tutarsızlığı: **yalnız SINIRSIZ** olanlara
  (boq + contracts aileleri) `roles/documents` emsali **2000** tavanı; şema düzeyinde
  (`DESCRIPTION_MAX_LENGTH` tek-kaynak deseni, BC emsali), kolon tipi DEĞİŞMEZ → migration YOK.
  Mevcut 500'ler (`units.notes` vb.) DOKUNULMAZ (sıkılaştırma kırıcı olur).

## 2. Kapsam DIŞI
- `Base.naming_convention` — TB1 kararı: riskli, ayrı dilim (repo geneli autogenerate etkisi).
- P11/Gantt, yeni modüller, frontend işleri.
- Migration: hedef SIFIR migration (B1-B4 hiçbiri kolon açmıyor; `quantity_source` kolonları
  SD/TH'de zaten var).

## 3. Test odakları
B1: iki ailede damga senaryoları (eşit→diary · farklı→manual · taslak günlük sayılmaz · köprüsüz
poz→manual · yeniden PUT'ta damga tazelenir) · B2: tek-kaynak + ayrışma-üretme denemesi ·
B3: PATCH sonrası BOQ satırı senkron + miktar korunumu · B4: 2000/2001 sınır değerleri iki uçta.

## 4. Etkilenen yüzeyler (kırıcılık)
B1 additive (yanıt alanı zaten var, değeri anlamlanıyor) · B2/B4 davranış-nötr · B3 BOQ okuma
yanıtlarında değer düzeltmesi (şema değişmez). openapi'de şema farkı yalnız B4 `maxLength`
kısıtları — devir sonraki frontend diliminin T1'inde (P10 borcuyla birlikte).

## 4b. T1'de alınan EK kararlar (kullanıcı onayı 2026-08-09 — yeniden tartışılmaz)
- **S4 — işveren yanıt simetrisi:** `quantity_source`, işveren `ProgressPaymentLineDetail`
  yanıtına da EKLENİR; iki ailenin satır şeması bu alanda simetriktir. Aksi hâlde damga
  sunucuda doğru basılır ama hiçbir istemci göremezdi (borç fiilen kapanmazdı). Additive,
  kırıcı değil; openapi farkı zaten B4 ile birlikte devrolur. Alanın yanıtta göründüğü
  İKİ ailede de testlidir.
- **S5 — dönemsiz hakediş:** `period_year` NULL olan hakediş DAMGALANMAZ (`manual`).
  Dönemi olmayan bir evrakı "tüm zamanların" günlük toplamıyla kıyaslamak uydurma bir
  kaynak iddiası üretirdi.
- **S6 — şantiyesiz sözleşme:** `site_id` NULL (proje-geneli) taşeron sözleşmesinde damga
  BASILMAZ (`manual`) — öneri ucunun S5 kapsam kuralının (`SUGGESTION_CONTRACT_WITHOUT_SITE`)
  yazma-yolu karşılığıdır: hangi şantiyenin günlüğüne bakılacağı belirsizdir.

## 5. AÇIK SORULAR (kullanıcı cevabı ŞART)
- **S1 — SD-2 eşleşme kuralı:** öneri: dönem+poz bazında **birebir eşitlik** → `diary`; kısmi/
  yaklaşık eşleşme `manual` kalır (yarı-günlük miktara damga basmak yanıltıcı). Dönem = hakedişin
  kendi dönemi; taslak günlükler sayılmaz.
- **S2 — B3 yönü:** öneri: **senkron tazeleme** (ayna alanlar kusur kaydıydı, snapshot kararı
  değildi). Alternatif: "bilinçli snapshot" ilan edip borcu kapatmak (önerilmez — iki ekran
  çelişkisi sürer).
- **S3 — Metin tavanı:** öneri: yalnız sınırsız alanlara 2000 (migration'sız, şema katmanı).
  Alternatif: hepsini tek standarda çekmek (500'leri gevşetmek — gereksiz).
