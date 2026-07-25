# B6 — Gösterge Paneli uçları (tasarım)

Tarih: 2026-07-25
Kapsam: Alt-Proje 1 (Temel), son backend fazı
Mockup kanonu: `projedesign/Ekran 1 - Gösterge Paneli.dc.html`
Bağlı ana spec: `2026-07-17-temel-modul-design.md` §4.1, §7, §8

---

## 1. Amaç

Gösterge paneli ekranının (F6) ihtiyaç duyduğu tek okuma ucunu yazmak. Yeni tablo yok,
yeni migration yok — mevcut `projects` ve `user_project_access` tabloları okunur.

Ana spec §7'nin kararı geçerlidir: **kabuk gerçek, veri dürüst.** Proje kartları gerçek
veriyle dolar; veri kaynağı henüz yazılmamış beş kart (portföy, tahsil edilecek, ortalama
marj, onay bekleyenler, risk) boş durum döner. Sahte/seed rakam üretilmez.

## 2. Uç

```
GET /dashboard/summary
```

Kapı: `require_permission("dashboard", AccessLevel.view)`.

Mevcut `GET /projects` ucuna **dokunulmaz**. O uç `user_management` iznine bağlı ve
Ayarlar ekranları için doğru kapıdır; gösterge paneli kendi iznini kullanır.

### 2.1 Kapsam süzgeci

Projeler `user_project_access` üzerinden süzülür:

| Aktörün erişim satırları | Dönen projeler |
|---|---|
| `all_projects = true` satırı var | tüm projeler |
| yalnızca `project_id` satırları | yalnızca o projeler |
| hiç satır yok | boş liste |

`role_permissions.scope` bu uçta **kullanılmaz**. Scope, modül içi kayıt kapsamını
tanımlar; proje görünürlüğünün tek kaynağı `user_project_access`'tir (ana spec §4.1).

### 2.2 Yanıt gövdesi

```jsonc
{
  "role_name": "Patron",
  "active_project_count": 2,
  "projects": [
    {
      "id": "…",
      "code": "GK-A",
      "name": "Güneşkent A-Blok",
      "status": "active",
      "budget": "1500000.00",
      "progress_pct": "42.50"
    }
  ],
  "portfolio":         { "available": false, "value": null, "pending_module": "progress_payments" },
  "receivables":       { "available": false, "value": null, "pending_module": "invoicing" },
  "average_margin":    { "available": false, "value": null, "pending_module": "progress_payments" },
  "pending_approvals": { "available": false, "count": 0, "items": [], "pending_module": "approvals" },
  "risks":             { "available": false, "items": [], "pending_module": "inventory" }
}
```

**`role_name`** — aktörün rolünün görünen adı. Mockup'taki breadcrumb "Patron Görünümü"
buradan türetilir. Rol adı kullanıcı tarafından değiştirilebilir (ana spec §4.1), bu yüzden
`key` değil `name` döner.

**`active_project_count`** — görünür projeler içinde `status = active` olanların sayısı.
Mockup'taki "4 Aktif Proje" ifadesinin karşılığı.

**`projects`** — kart başına gereken alanlar. Sıralama `code` artan (mevcut repository
davranışı). Filtre/sayfalama yok: gösterge paneli tüm görünür projeleri basar.

### 2.3 Yer tutucu sözleşmesi

Beş kartın hepsi aynı iki şekilden birini kullanır:

```python
class MetricPlaceholder(BaseModel):   # portfolio, receivables, average_margin
    available: bool
    value: Decimal | None
    pending_module: str

class ListPlaceholder(BaseModel):     # risks
    available: bool
    items: list[...]                  # v1'de daima []
    pending_module: str

# pending_approvals = ListPlaceholder + count: int
```

`available` alanı bilinçli olarak vardır. F6 sabit bir `false` sabitine değil **veriye**
dallanır; ilgili alt-proje geldiğinde backend `available: true` döndürmeye başlar ve
frontend'de tek satır değişmez.

`pending_module` bir **modül anahtarıdır**, kullanıcıya gösterilecek metin değil.
"Hakediş modülüyle birlikte gelir" gibi Türkçe kopya frontend'in sorumluluğundadır —
backend metin üretmez.

v1'de `available` her zaman `false`, `value` her zaman `null`, `items` her zaman `[]`,
`count` her zaman `0`'dır. Bunlar servis katmanında tek yerde üretilir; router bilmez.

## 3. Yerleşim

```
app/modules/dashboard/
├── __init__.py
├── router.py      # tek uç, izin kapısı, şema doğrulama
├── service.py     # kapsam süzgeci + yer tutucu üretimi
└── schemas.py     # DashboardSummaryResponse ve alt şemalar
```

`repository.py` **yok** — sorgular mevcut `projects` ve `users` repository'lerinden
kullanılır. Yeni sorgu gerekiyorsa (`list_projects_for_user`) ilgili modülün kendi
repository'sine eklenir; dashboard modülü veri erişimi sahiplenmez.

`app/main.py`'a `dashboard_router` eklenir.

## 4. Denetim günlüğü

Kayıt **yazılmaz**. B5 yalnızca durum değiştiren işlemleri (login, create, update, delete,
approve, backup) kaydeder; okuma uçları kapsam dışıdır. Gösterge paneli her sayfa
açılışında çağrılacağı için kayıt yazmak günlüğü anlamsızca şişirirdi.

## 5. Hatalar

| Durum | Yanıt |
|---|---|
| Oturum yok / token geçersiz | 401 (mevcut `get_current_user`) |
| `dashboard` izni `view` altında | 403 "Bu işlem için yetkiniz yok" |
| Erişilebilir proje yok | 200, `projects: []`, `active_project_count: 0` |

Boş proje listesi bir hata değildir — yeni kurulan şirkette normal durumdur (ana spec §7).

## 6. Testler

TDD, hedef ≥%80 kapsam.

| Test | Beklenen |
|---|---|
| İzinsiz rol çağırır | 403 |
| Kimliksiz çağrı | 401 |
| `all_projects=true` kullanıcı | tüm projeler döner |
| Yalnızca 1 projeye erişimli kullanıcı | yalnızca o proje döner |
| Erişim satırı olmayan kullanıcı | boş liste, sayaç 0 |
| Karışık durumlu projeler | `active_project_count` yalnızca `active` sayar |
| Yer tutucular | beşi de `available=false`, doğru `pending_module` |
| Sıralama | `code` artan |

Testler lokal Postgres'te koşar (brew `postgresql@18`, port 5432). `backend/.env`
içindeki `TEST_DATABASE_URL` uzak Railway host'unu gösteriyor ve conftest ona `drop_all`
uyguluyor — **oraya asla koşturulmaz**.

## 7. Teslim sonrası

`openapi.json` üretilir → `frontend/openapi/openapi.json`'a kopyalanır → `pnpm gen:api`.
Akış `backend/README.md`'de.

## 8. Kapsam dışı

Ana spec §7 gereği, aşağıdakiler bu fazda **yazılmaz**; ilgili alt-proje geldiğinde
`available: true` dönmeye başlarlar:

| Kart | Bağlı alt-proje |
|---|---|
| Portföy · Toplam Hakediş + 6 aylık seri | Alt-Proje 3 |
| Tahsil Edilecek | Alt-Proje 6 |
| Ortalama Marj | Alt-Proje 3 + 6 |
| Onay Bekleyenler | Alt-Proje 7 |
| Risk & Uyarılar | Alt-Proje 2/3/5 |

Ayrıca bu fazda yapılmayanlar: `projects` yazma ucu, `projects.type` sütunu ve proje tipi
taksonomisi, `company_assets` modülü. Gerekçeleri ana spec §4.1 ve §8'deki Alt-Proje 2
kapsam notlarında.
