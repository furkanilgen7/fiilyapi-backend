"""Araç kataloğu — **TEK KAYNAK** (spec §5.2, AI-0b dilimi).

Dört araç üç kapı sınıfını da sınar, artı `navigate_to` ve `yetkilerim`.

🔴 **Dinamik/gecikmeli araç yükleme REDDEDİLDİ.** Canlı kusurun kök sebebi tam
olarak "prompt araçları eksik listeliyordu"ydu (S9). Katalog her turda TAM
listelenir; prompt uzunluğu sorun olursa çözüm **açıklamaları kısaltmaktır,
listeyi değil**.

🔴 **`PROPOSE_TOOLS` boş ama dallanma ŞİMDİ yazılır** (spec T5). Boş bir liste
"kapı çalışıyor"u kanıtlamaz; bu yüzden testler **sahte** bir propose aracıyla
kapıyı ölçer (`patron` = matriste `_V`, `_F` bile olsa göremez).

## Yönetişim denylist'i (S16/S17, bekçi B26)

`{user_management, settings, approvals, roles}` modüllerine **dokunan** hiçbir
araç kaydedilemez... **bir istisnayla**: `onay_kutum` `approvals` modülünün
`GET /approvals` ucunu sarar ama o uç **kapısızdır** (`kapilar == ∅`) ve
denylist kapı modülleri üzerinden çalışır. Yani denylist "yazma yüzeyine dokunma"
kuralıdır ve `onay_kutum` hiçbir kapı beyan etmediği için ona takılmaz. Bu
inceliğin kendisi bekçilenir: `onay_kutum`a `("approvals", view)` kapısı
eklenirse B26 kırmızı olur.
"""

from __future__ import annotations

import uuid
from typing import Final

from app.core.access import AccessLevel
from app.modules.ai.registry import ToolKapsami, ToolKumesi, ToolRegistry, ToolSpec
from app.modules.ai.tools import schemas
from app.modules.ai.tools.reads import handlers

#: 🔴 Bu modüllerin **kapısını** taşıyan hiçbir araç kaydedilemez (B26).
#: Gerekçe S17: "yalnız sysadmin yazar" cümlesi, AI'ın izin matrisini yeniden
#: yazabilmesi demek DEĞİLDİR. Tek kabul edilen öneri kalıcıdır — eşik
#: 500.000 → 999.999.999 yapılırsa Patron adımı bir daha asla eklenmez ve ekran
#: hiçbir anda "bozuldu" demez.
YONETISIM_DENYLIST: Final[frozenset[str]] = frozenset(
    {"user_management", "settings", "approvals", "roles"}
)


PROJELERI_LISTELE = ToolSpec(
    ad="projeleri_listele",
    aciklama=(
        "NE ZAMAN: kullanıcı projelerini, proje kodunu/adını ya da kaç projesi "
        "olduğunu sorduğunda. NE SORMAZ: bütçe/ilerleme detayı, maliyet, kâr. "
        "Dönen liste kullanıcının GÖRÜNÜR projeleridir; boş küme 'proje yok' "
        "DEĞİL 'senin kapsamında yok' anlamına gelebilir."
    ),
    kapsam=ToolKapsami.MODUL_KAPISI,
    kume=ToolKumesi.PROJE_KAPSAMLI,
    kapilar=frozenset({("projects", AccessLevel.view)}),
    ucler=("/projects",),
    #: `ProjectListItem` alanları — kişisel veri YOK, hepsi `projects`.
    veri_modulleri=frozenset({"projects"}),
    yol_parametreleri={},
    girdi=schemas.BosGirdi,
    yanit_modeli=schemas.AiProjeListesi,
    calistir=handlers.projeleri_listele,
)

ONAY_KUTUM = ToolSpec(
    ad="onay_kutum",
    aciklama=(
        "NE ZAMAN: kullanıcı 'onayımda ne var', 'imzam bekleyen' diye sorduğunda. "
        "NE SORMAZ: onaylama/reddetme — bu araç YALNIZ OKUR. Dönen küme zaten "
        "'bu adım SANA düştü' olgusuyla sınırlıdır; boş olması yetki reddi DEĞİLDİR."
    ),
    # 🔴 Kapının MEKANİK TÜRETİLEMEYECEĞİNİN canlı vakası. Router: "Ayri bir
    # yetki kapisi YOKTUR ve olmamalidir".
    kapsam=ToolKapsami.KENDI_KUMESI,
    kume=ToolKumesi.PROJE_KAPSAMLI,
    kapilar=frozenset(),
    ucler=("/approvals",),
    #: 🔴 `kapilar` BOŞ ama veri BOŞ DEĞİL. Kutu üç evrak ailesinin künyesini
    #: taşır (`progress_payments` + `procurement`) ve evrağı YARATANIN adını
    #: (`created_by_name`) basar. `kapilar`dan türeten bir sistem burada
    #: "hiçbir modülün verisi" derdi — ölçülmüş deliğin ta kendisi.
    veri_modulleri=frozenset({"approvals", "progress_payments", "procurement"}),
    yol_parametreleri={},
    girdi=schemas.BosGirdi,
    yanit_modeli=schemas.AiOnayKutusu,
    calistir=handlers.onay_kutum,
)

PUANTAJ_HAFTASI = ToolSpec(
    ad="puantaj_haftasi",
    aciklama=(
        "NE ZAMAN: belirli bir şantiyenin belirli bir ISO haftasındaki puantaj "
        "özeti sorulduğunda. NE SORMAZ: kişi bazlı gün kodları, ücret, bordro. "
        "Şantiyeye erişimin yoksa 'kayıt yok' cevabı gelir — bu, şantiyenin var "
        "olmadığı anlamına GELMEZ."
    ),
    kapsam=ToolKapsami.MODUL_KAPISI,
    kume=ToolKumesi.PROJE_KAPSAMLI,
    kapilar=frozenset({("timesheet", AccessLevel.view)}),
    ucler=("/sites/{site_id}/timesheet/week",),
    #: Haftalık özet şantiye + proje adını da basar; `personnel` **taşımaz**
    #: (kişi bazlı gün kodu araç şemasında YOK — `aciklama` bunu söyler).
    veri_modulleri=frozenset({"timesheet", "sites", "projects"}),
    yol_parametreleri={"site_id": uuid.UUID},
    girdi=schemas.PuantajHaftasiGirdi,
    yanit_modeli=schemas.AiPuantajHaftasi,
    calistir=handlers.puantaj_haftasi,
)

GOSTERGE_OZETI = ToolSpec(
    ad="gosterge_ozeti",
    aciklama=(
        "NE ZAMAN: 'genel durum', 'özet', 'panelde ne var' sorulduğunda. "
        "NE SORMAZ: tek bir projenin detayı. ⚠️ Bu yanıttaki proje sayıları ÜÇ "
        "AYRI ŞEYİ sayar ve birbirinden TÜRETİLEMEZ; risk kartı sessizce kırpılır "
        "ve toplam sayı BİLDİRMEZ."
    ),
    kapsam=ToolKapsami.MODUL_KAPISI,
    # 🔴 `SIRKET_GENELI`nin İLK GERÇEK KULLANIMI — ve bir DÜZELTMEdir.
    #
    # Bu araç `PROJE_KAPSAMLI` beyan ediyordu; ölçüm bunu çürüttü. Zincir:
    # `dashboard/service.py::_risks` → `dashboard/risks.py::build_risks` →
    # `_stock_alerts` → `inventory/repository.py::visible_warehouse_ids` →
    # `_warehouse_scope`, ve o süzgeç **İKİ DALLI ve OR**'ludur:
    #
    #     Warehouse.site_id.is_(None) | Warehouse.site_id.in_(gorunen_santiyeler)
    #
    # Yani MERKEZ DEPO (`site_id IS NULL`) kapsam süzgecine **TABİ DEĞİLDİR** —
    # `_warehouse_scope` docstring'i bunu bilinçli bir karar olarak yazar
    # ("Merkez dalı OR'dan çıkarılsaydı şirketin ana ambarı hiç kimseye
    # görünmezdi"). Sonuç: `risk_notu`daki sayı, aktörün HİÇBİR projesine bağlı
    # olmayan satırları içerebilir. `equipment/repository.py::scope` de birebir
    # aynı OR'u taşır — desen tek değil, ikizdir.
    #
    # Kartın öbür yarısı (`portfoy`, `gorunur_proje_sayisi`) gerçekten proje
    # kapsamlıdır; yani araç KARIŞIKTIR. Fail-closed okuma `SIRKET_GENELI`dir:
    # kapsam notunun işi modelin "senin kapsamında" demesini engellemektir ve
    # yanıtın **bir bölümü** bile kapsam dışıysa o cümle yalan olur.
    #
    # ⚠️ Ve not TERSİNE ÇEVRİLEMEZ: dolu bir küme kapsam iznini KANITLAMAZ.
    # `guards.KAPSAM_NOTLARI["sirket_geneli"]` bunu açıkça söyler.
    kume=ToolKumesi.SIRKET_GENELI,
    kapilar=frozenset({("dashboard", AccessLevel.view)}),
    ucler=("/dashboard/summary",),
    #: 🔴 TEK KAPI, BEŞ MODÜL — kapıdan türetmenin çürütüldüğü vaka.
    #: `_portfolio` → `progress_payments`; `_risks` → `inventory` + `sites` +
    #: `progress_payments`; `projects` dizisi ve iki sayaç → `projects`.
    veri_modulleri=frozenset({"dashboard", "projects", "progress_payments", "inventory", "sites"}),
    yol_parametreleri={},
    girdi=schemas.BosGirdi,
    yanit_modeli=schemas.AiGostergeOzeti,
    calistir=handlers.gosterge_ozeti,
)

YETKILERIM = ToolSpec(
    ad="yetkilerim",
    aciklama=(
        "NE ZAMAN: bir sorunun cevabını verebilmek için önce kullanıcının neyi "
        "görebildiğini bilmen gerektiğinde, ya da kullanıcı yetkisini sorduğunda. "
        "NE SORMAZ: başka bir kullanıcının yetkisi. Listede olmayan bir modül "
        "'yok' DEMEK DEĞİLDİR — izin satırı olmayan modül burada hiç görünmez."
    ),
    kapsam=ToolKapsami.KENDI_KUMESI,
    kume=ToolKumesi.KAPSAMSIZ,
    kapilar=frozenset(),
    ucler=("/auth/me",),
    #: Yalnız aktörün KENDİ izin haritası. `users` bir izin modülü değildir;
    #: taşıdığı tek şey `ai` modülünün kendi meta verisidir.
    veri_modulleri=frozenset({"ai"}),
    yol_parametreleri={},
    girdi=schemas.BosGirdi,
    yanit_modeli=schemas.AiYetkilerim,
    calistir=handlers.yetkilerim,
)

NAVIGATE_TO = ToolSpec(
    ad="navigate_to",
    aciklama=(
        "NE ZAMAN: kullanıcının istediği şey bir ekranda yapılıyorsa ve elinde "
        "uygun bir veri aracı YOKSA. NE SORMAZ: veri — bu araç hiçbir kayıt "
        "okumaz, yalnız bir ekran önerir. Eşleşen bir veri aracı yoksa "
        "çağırabileceğin TEK araç budur."
    ),
    kapsam=ToolKapsami.KENDI_KUMESI,
    kume=ToolKumesi.KAPSAMSIZ,
    kapilar=frozenset(),
    #: Hiçbir uca gitmez. Boş demet, `ReadOnlyTransport`un HER yolu reddetmesi
    #: demektir — yani bu araç bir GET denese fail-closed patlar.
    ucler=(),
    #: Hiçbir kayıt okumaz — beyan da boştur ve `dogrula_spec` bunu yalnız
    #: `ucler` boş olduğu için kabul eder.
    veri_modulleri=frozenset(),
    yol_parametreleri={},
    girdi=schemas.YonlendirGirdi,
    yanit_modeli=schemas.AiYonlendirme,
    calistir=handlers.navigate_to,
)


READ_TOOLS: Final[tuple[ToolSpec, ...]] = (
    PROJELERI_LISTELE,
    ONAY_KUTUM,
    PUANTAJ_HAFTASI,
    GOSTERGE_OZETI,
    YETKILERIM,
    NAVIGATE_TO,
)

#: AI-3'e kadar BOŞ. Dallanma ve testi ŞİMDİ yazılır (spec T5).
PROPOSE_TOOLS: Final[tuple[ToolSpec, ...]] = ()

CATALOG: Final[tuple[ToolSpec, ...]] = (*READ_TOOLS, *PROPOSE_TOOLS)

REGISTRY: Final[ToolRegistry] = ToolRegistry(READ_TOOLS, PROPOSE_TOOLS)
