# P11 — Proje Takvimi / Gantt (backend spec)

Tarih: 2026-08-11 · Durum: **ONAYLANDI (2026-08-11)** — §6'nın BEŞ sorusu da önerildiği gibi:
S1 ilerleme %'leri basılmaz/pending (bar durum renginden) · S2 milestone minimal title+date,
"Tamamlandı" türev · S3 tek öncül, yalnız bilgi, aynı şantiye, döngü 422 · S4 timeline HAM veri ·
S5 "Gantt'a otomatik ekle" kolonu AÇILMAZ (form artefaktı; F tarafında devre-dışı basılır).
Mockup: `Proje Takvimi.dc.html` (**PT**, 310 satır — portföy Gantt'ı) · `Form - Bolum Ekle.dc.html`
(**BE** — giriş tarafı: 115-117 bağımlılık select'i · 120-125 milestone girişi · 69 "Gantt sıralaması" ·
237-238 otomatik ekleme checkbox'ı) · `Ekran 14` 98-123 milestone takvimi · `Ekran 6` 147-168 yaklaşan
milestone'lar. Bağlam: P6 kalıcı kararı — "bağımlılık/milestone/Gantt → P11".

## 1. Kapsam ve ana gerçek

PT ekranı **%100 salt gösterim** (0 input/select; 6 statik buton). Satır birimi **Proje → Faz/Bölüm**
iki seviye (şantiye seviyesi YOK); bar verisi = ad + tarih aralığı + durum rengi (+ % etiketi — §6 S1).
Giriş yüzeyi yalnız BE formunda çizili: bağımlılık (tek öncül select) + milestone (ad+tarih).
**P11 = 1 kolon + 1 tablo + 1 okuma ucu + bölüm gövdesi genişlemesi.** Yeni izin modülü YOK
(`projects:view` okuma · `sites` yazma — bölüm formunun mevcut izni).

## 2. Şema (tek migration)

- `sections.depends_on_section_id` — self-FK, nullable, `ondelete=SET NULL` (BE 115-117 tek öncül;
  çoklu bağımlılık ÇİZİLMEMİŞ, liste tablosu AÇILMAZ).
- **YENİ** `section_milestones`: `id` · `section_id` FK→sections CASCADE · `title` String(200)
  (BE 121 "Kat 14 döşeme tamamlanması") · `milestone_date` Date (BE 122) · `sort_order`.
  **Durum kolonu YOK** (§6 S2): "Tamamlandı" görünümü türevdir. Proje görünürlüğü bölüm üzerinden.
- BE 237 "Gantt'a otomatik ekle" checkbox'ı: kolon AÇILMAZ — timeline zaten tüm bölümleri basar;
  hariç tutma kavramı başka hiçbir ekranda yok (işaretli-varsayılan artefakt sayılır, §6 S5).

## 3. Uçlar

| Uç | İçerik |
|---|---|
| **YENİ** `GET /projects/timeline` | Portföy Gantt verisi (`visible_projects`): proje satırı (ad · start/end · sözleşme bedeli · durum) + bölüm satırları (ad · tarihler · durum · `sort_order` · `depends_on_section_id`) + milestone'lar (title+date) + `today`. HAM veri — ay ızgarası/zoom/bar genişliği İSTEMCİ işi (§6 S4). Deterministik sıra; N+1 yok (tek yükleme, TB3 sayaç testi) |
| `POST/PATCH sections` genişleme | `depends_on_section_id` (aynı ŞANTİYE şartı 422 · self/döngü 422 — zincir yürüyerek) + `milestones` listesi **id-korunumlu birleştirme** (P9 `ShareholderInput.id` emsali; ayrı CRUD ucu AÇILMAZ) |
| Bölüm/section okuma yanıtları | `depends_on_section_id` + `milestones` alanları (additive) |

Bağımlılık **yalnız bilgidir** (BE 117 "Gantt'ta bağlantı çizgisi"): tarih kısıtı ZORLANMAZ
(öncül bitmeden başlayan bölüm 422 ALMAZ — mockup'ta böyle bir kural yok, icat edilmez).
Bölüm silinince bağımlılar `SET NULL` (bilgi bağı, engel değil); milestone'lar CASCADE.

## 4. Kapsam dışı / pending (icat yasağı)

- **İlerleme yüzdeleri** (PT 159 proje %75 · 187 faz %62): kaynak TANIMSIZ (hiçbir giriş/hesap yok) —
  §6 S1'e bağlı: basılmaz/pending. Bar DURUMU bölüm `status`undan türer (completed/active/planned —
  PT legend 49-51 ile birebir).
- Zoom kipleri (Aylık/Haftalık/Yıllık), ‹/›/Bugün gezinme, collapse — istemci işi; backend ay
  parametresi almaz (S4).
- Gecikme vurgusu · kritik yol (E6 153 tek metin) · baseline kıyası → pending (kaynak yok).
- E6 "Yaklaşan Milestone'lar" ekran bölümü → o ekranın frontend dilimi timeline/section verisinden
  türetir; ayrı uç AÇILMAZ (hakediş milestone'u E6 160 = hakediş kaydı türevi, tablo karışmaz).
- PT 300-303 portföy özeti: mevcut verilerin türevi, timeline yanıtına ayrıca konmaz (dashboard işi).

## 5. Test odakları

Döngü tespiti (self · 2'li · 3'lü zincir) 422 · şantiye-dışı öncül 422 · milestone kimlik korunumu
(id'li güncellemede satır id değişmez) · bölüm silme → milestone CASCADE + bağımlı SET NULL ·
timeline IDOR (görünmez proje yanıtta YOK) · N+1 ölçümü · migration turu.

## 6. AÇIK SORULAR (kullanıcı cevabı ŞART)

- **S1 — İlerleme yüzdeleri:** kaynak tanımsız. Öneri: **basılmaz/pending** — bar yalnız durum
  rengiyle (bölüm status'u); % etiketi ileride hakediş/BOQ ilerlemesine bağlanır. Alternatif:
  bölüme elle `progress_pct` kolonu (formda karşılığı YOK — icat, önerilmez).
- **S2 — Milestone modeli:** öneri: minimal `title`+`date` (BE girişi birebir); "Tamamlandı" rozeti
  `date < today` TÜREVİ, durum kolonu yok. Alternatif: elle işaretlenen durum (formda yok — icat).
- **S3 — Bağımlılık semantiği:** öneri: tek öncül + yalnız bilgi (tarih kısıtı zorlanmaz) + aynı
  şantiye şartı + döngü 422. Alternatif: tarih zorlaması (mockup'ta yok — önerilmez).
- **S4 — Timeline ucu ham veri:** öneri: ay/zoom parametresi YOK, istemci çizer. Alternatif:
  sunucu tarafı ay ızgarası (gereksiz bağlayıcılık).
- **S5 — BE 237 "Gantt'a otomatik ekle" checkbox'ı:** öneri: kolon açılmaz, kutu form artefaktı
  sayılır (hariç tutma kavramı hiçbir görünümde yok); F-P11/F-P6 formunda devre-dışı basılır.
  Alternatif: `include_in_timeline` kolonu (yalnız bu kutu için — şişkinlik).
