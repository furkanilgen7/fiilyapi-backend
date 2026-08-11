# ST — Stok Çekirdeği (backend spec)

Tarih: 2026-08-11 · Durum: **ONAYLANDI (2026-08-11)** — §7'nin ALTI sorusu da önerildiği gibi:
S1 formül (%50·min / min / 5×min; veriden türetilmiş) · S2 `warehouses` + S2b merkez depo izinle
görünür · S3 `supplier_name` serbest metin · S4 transfer çift bacak + adjustment negatif + eksi
bakiye engellenmez · S5 seed'de varsa o, yoksa 21. modül `inventory` · S6 son giriş fiyatı × bakiye.
Mockup: `Ekran 3 - Stok & Depo.dc.html` (**E3**) · `Şantiye - Stok.dc.html` (**ŞS**) ·
`Form - Stok Girisi.dc.html` (**SG**). Satınalma mockup'ları (`Satınalma*`, `Form - Satinalma Talebi`)
**SA dilimine** — bu spec sınırı korur.

## 1. Kapsam

Stok çekirdeği: malzeme kartı kataloğu + depolar + giriş hareketleri + türev bakiyeler/durumlar +
genel (E3) ve şantiye (ŞS) liste verileri. **Satınalma bağları (sipariş/tedarikçi kataloğu/otomatik
bildirim/acil sipariş) SA dilimine pending**; belge yüklemeleri (SG 149-172) BC form-slot bağına
pending. "+ Malzeme Ekle" ve "Stok Hareketi" EKRANLARI çizilmemiş — backend uçları veri modelinden
açılır, frontend formları F-ST'de (gerekirse mockup istenir).

## 2. Şema (tek migration)

- **`stock_items`** (katalog; SG 134 "stok kartı"): `code` String(30) UQ (SNK-0421 deseni — SERBEST,
  önek zorlanmaz) · `name` String(200) · `category` enum `stock_category(structural, steel,
  electrical, mechanical, interior)` (E3 99 select + tablo: Yapı Malzemesi · Demir-Çelik · Elektrik ·
  Mekanik · İç Yapı) · `unit` String(20) (Ton/Torba/Metre/Adet/m³ — SERBEST metin; enum İCAT
  EDİLMEZ, mockup kümesi açık uçlu) · `min_stock` Numeric nullable (E3 115) · `is_active`.
- **`warehouses`** (§7 S2): `name` String(100) · `site_id` FK→sites SET NULL **nullable**
  ("Merkez Depo (Sincan)" şantiyesiz — SG 84) · UQ (site_id, name). Seed YOK (D-1/D-2/D-3 örnek veridir).
- **`stock_entries`** (hareket başlığı; SG): `entry_type` enum `stock_entry_type(purchase, transfer,
  adjustment)` (SG 53-76) · `entry_date` · `warehouse_id` FK RESTRICT · `source_warehouse_id` FK
  nullable (§7 S4 — yalnız transfer) · `supplier_name` String(200) nullable (§7 S3 — serbest metin) ·
  `delivery_note_no` String(50) nullable (SG 87 İrsaliye) · `received_by_user_id` FK users SET NULL
  (SG 88) · `note` Text(2000 şema tavanı) (SG 169; TB4 standardı).
- **`stock_entry_lines`**: `entry_id` CASCADE · `item_id` FK RESTRICT · `quantity` Numeric
  (adjustment'ta NEGATİF olabilir — §7 S4; diğer tiplerde >0) · `unit_price` Numeric nullable ·
  `quality` enum `stock_quality(ok, defective, rejected)` (SG 117 ✓/⚠/✗) · satır tutarı TÜREV
  (kolon açılmaz).
- **İzin modülü (§7 S5):** İzin Matrisi mockup'unda "STOK & SATINALMA / Stok & Depo" satırı VAR —
  seed'de anahtar hazırsa o kullanılır; yoksa **21. modül `inventory`** açılır (seed+migration+matris
  testi birlikte — bilinen tuzak).

## 3. Türevler

- **Bakiye** = hareket toplamı (kolon YOK): depo bazında SUM(lines.quantity); transfer çift bacak
  (§7 S4) sayesinde toplam tutarlı. Şantiye bakiyesi = o şantiyenin depoları; genel = hepsi.
- **Durum** (E3 Kritik/Düşük/Normal/Fazla · ŞS Kritik/Düşük/Yeterli): `min_stock` üzerinden formül —
  §7 S1. `min_stock` yoksa durum `None` (uydurma yok).
- **KPI'lar** (E3 72-89 / ŞS 86-91): toplam stok değeri (§7 S6) · kritik/düşük sayaçları · toplam
  kalem. "Bekleyen Sipariş" SA'ya pending zarfla.
- **Listeler:** E3 = katalog + toplam bakiye + depo kırılımı; filtreler durum/kategori/`q`.
  ŞS = şantiye bakiyesi; **"Aylık İhtiyaç" ve "Bölüm" sütunları PENDING** (hiçbir giriş yüzeyi yok —
  ileride planlama/BOQ türevi; uydurulmaz).

## 4. Uçlar (izin: stok modülü; IDOR `visible_projects` — merkez depo §7 S2b)

`GET/POST /stock/items` + `PATCH /stock/items/{id}` (DELETE YOK — hareketi olan kart silinemez;
`is_active=false`) · `GET/POST /warehouses` + `PATCH` (DELETE yalnız hareketsizken, admin) ·
`POST /stock/entries` (başlık+satırlar tek gövde, atomik; SG formu birebir — sipariş alanları HARİÇ) ·
`GET /stock/entries` (liste; tip/depo/tarih süzgeci — "Stok Hareketi" ekranının verisi) ·
`GET /stock/summary` + `GET /sites/{id}/stock` (E3/ŞS listeleri + KPI). Audit: giriş başına TEK olay.

## 5. Kapsam dışı / pending (icat yasağı)

Sipariş bağı (SG 85/95/113 "Sipariş" sütunu dahil) · tedarikçi kataloğu · "eksik teslimat" oto-bildirim
(SG 176) · Acil Sipariş/Satınalma Talebi butonları → **SA dilimi**. Belge alanları (SG 149-166) →
BC form-slot. ŞS "Aylık İhtiyaç"/"Bölüm" → pending. Çıkış/sarf FORMU yok → ayrı sarf ucu AÇILMAZ
(§7 S4). E1/E6/AI/bildirim entegrasyonları → kendi dilimleri.

## 6. Test odakları

Bakiye türevi (giriş+transfer+negatif düzeltme senaryoları; eksi bakiye davranışı §7 S4) ·
durum formülü sınır değerleri (E3'ün 7 örnek satırı BİREBİR senaryo) · atomiklik (bozuk satır →
hiçbir şey yazılmaz) · IDOR (şantiye deposu görünmeyen projede 404) · transfer çift bacak tutarlılığı ·
izin matrisi (view/full/admin) · N+1 ölçümü (liste uçları).

## 7. AÇIK SORULAR (kullanıcı cevabı ŞART)

- **S1 — Durum formülü:** mockup eşik tanımlamıyor ama 7 örnek satır ŞU formüle BİREBİR oturuyor:
  `kritik: bakiye < %50×min` (demir 0,24 · PP-R 0,375 · NYY-ŞS 0,32) · `düşük: < min` (NYY 0,8) ·
  `fazla: > 5×min` (alçı 5,6) · arası `normal/yeterli` (çimento 4,2 · tuğla 2,48). Öneri: bu formül,
  tek kaynak sabitlerle + "veriden türetilmiş, kullanıcı onaylı" notuyla. Alternatif: yalnız
  kritik(<min)/normal — düşük+fazla pending.
- **S2 — Depo modeli:** öneri: `warehouses` tablosu, `site_id` nullable (merkez depo). **S2b:**
  merkez depo (şantiyesiz) görünürlüğü — öneri: stok modül İZNİ olan herkes görür (proje kapsamı
  yalnız şantiyeli depolara uygulanır).
- **S3 — Tedarikçi:** öneri: `supplier_name` SERBEST METİN; SA dilimi tedarikçi tablosunu açınca
  FK göçü o dilimin işi (geriye dönük eşleme yapılmaz). Alternatif: şimdiden mini `suppliers` tablosu.
- **S4 — Transfer + çıkış semantiği:** SG yalnız GİRİŞ çizmiş; sarf/çıkış formu YOK. Öneri:
  (a) `transfer` tipinde `source_warehouse_id` ZORUNLU ve kaynak depodan aynı miktarda otomatik
  DÜŞÜŞ (çift bacak — yoksa transfer stok yaratır, toplam şişer); (b) `adjustment` satırları
  negatif olabilir (sayım farkı/iade/sarf tek kapısı); (c) eksi bakiye ENGELLENMEZ, yalnız
  raporlanır (katı engel sayım düzeltmesini kilitler). Ayrı sarf ucu AÇILMAZ.
- **S5 — İzin modülü:** öneri: seed'de stok anahtarı varsa o; yoksa 21. modül `inventory`
  (mockup'ta matris satırı VAR — BC'deki gibi sapma bile değil).
- **S6 — "Toplam Stok Değeri" fiyat kaynağı:** öneri: kalemin SON giriş `unit_price`ı × bakiye
  (ağırlıklı ortalama maliyet İCAT EDİLMEZ; fiyatsız kalem değere girmez, ayrıca raporlanır).
  Alternatif: ağırlıklı ortalama (muhasebe dilimine bırakılabilir).
