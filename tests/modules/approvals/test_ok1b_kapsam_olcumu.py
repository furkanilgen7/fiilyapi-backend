"""OK-1B T0 — ÖLÇÜM TURU: iki yeni evrak ailesinin zincire GİRİŞ KOŞULLARI.

Bu dosya **kod yazmaz, karar vermez**. OK-1B'nin emrinde "fatura + bordro dönemi
zincire girer" yazıyordu; ölçüm o premise'i ÜÇ yerde çürüttü ve çürütmelerin
hepsi YAPISALDIR (isim/sayı eşlemesi değil). Bulgular burada **çalışan bekçi**
hâline getirildi, çünkü rapora yazılan bir bulgu bayatlar — teste çakılan
bayatlamaz.

## Bekçilerin ne işe yaradığı

Zincir motoru bir evrağı yalnızca **projesinden** kapsamlayabilir
(`approvals/documents.py::visible_document_clause`, OK-1A T4/IDOR). Süzgeç şu
şekildedir:

    document_id IN (SELECT id FROM <aile> WHERE project_id IN (görünen projeler))

Bu yüklem üç şeyi VARSAYAR ve üçü de bugün doğrudur:

1. her ailenin satırında **DOĞRUDAN** bir `project_id` kolonu vardır,
2. o kolon **NOT NULL**'dur,
3. dolayısıyla "projesi çözülemeyen zincir" = "görünmeyen zincir" (fail-closed).

🔴 **İki yeni aile bu varsayımı KARŞILAMIYOR** ve sessizce bağlanırlarsa ikisi de
YANLIŞ tarafa düşer:

**bordro dönemi** — `project_id` kolonu **HİÇ YOK** (şirket geneli İK varlığı).
Alt sorgu yazılamaz; aile süzgeçten DÜŞER ve zincir **hiçbir onay kutusunda
GÖRÜNMEZ** — yani ölü bir özellik doğar.

**fatura** — `project_id` **NULLABLE**. `project_id IS NULL` olan fatura alt
sorguyu KAÇIRIR ve kutuda görünmez; oysa `invoicing/service.py` aynı faturayı
"projesiz ⇒ modül izni olan herkese açık" sayar. **İki yüzey aynı evrak için
farklı cevap verir.**

Yani bu iki kusur "eksik özellik" değil, **sessiz ayrışma** üretirdi. Bekçiler
onları CI'da görünür kılar.

🔴 Her durum KENDİ testindedir. Bileşik yazılsaydı öndeki iddia bayatladığında
arkadakiler HİÇ KOŞMAZDI (bu turda üç kez ısırdı).

🔴 Beklenen metinler ELLE yazılmıştır; ölçülen değerler koddan İTHAL EDİLİP
kendisiyle karşılaştırılmaz.

⚠️ `projedesign/` bu depoda YOKTUR (kök depoda durur) — mockup'ı OKUYAN bir test
yerelde de CI'da da dosya bulamazdı. Mockup bulguları bu yüzden RAPORDADIR,
testte değil.
"""

from app.modules.approvals.documents import DOCUMENT_PROJECT_COLUMNS
from app.modules.approvals.models import ApprovalDocumentType
from app.modules.invoicing.models import Invoice
from app.modules.payroll.models import PayrollPeriod
from app.modules.payroll.transitions import PERIOD_TRANSITIONS

#: 🔴 OK-1C'nin ÖLÇÜLMÜŞ rota gezgini — KOPYALANMAZ, İTHAL EDİLİR (DRY).
#: FastAPI 0.141'de `app.routes` doğrudan `APIRoute` vermez; ara katman
#: `_IncludedRouter`dır ve `.original_router.routes` ile açılır. Bu olgu
#: 2026-08-22'de OK-1C turunda kanıtlandı; ikinci bir kopya, gezgin
#: güncellendiğinde sessizce ayrışır ve bu dosya YANLIŞ şeyi ölçmeye başlardı.
#: Test modülleri arası private ithal deponun yerleşik deseni
#: (`test_ok1c_dar_kapsam.py` → `test_ok1c_ikame.py`).
from tests.modules.approvals.test_ok1c_dar_kapsam import _api_rotalari

# --------------------------------------------------------------------------- #
# 1. MOTORUN KAPSAM VARSAYIMI — zincire giren her aile projesinden süzülebilmeli
# --------------------------------------------------------------------------- #


def test_zincire_giren_HER_AILENIN_kapsam_kolonu_vardir():
    """`ApprovalDocumentType`ın her üyesi `DOCUMENT_PROJECT_COLUMNS`ta olmalıdır.

    🔴 BU TESTİN ASIL İŞİ İLERİYE DÖNÜKTÜR. Bugün üç üye var ve üçü de eşlemede.
    `ApprovalDocumentType`a yeni bir üye eklenip eşlemeye eklenmezse
    `visible_document_clause`ın `or_(...)` gövdesi o aile için HİÇBİR dal
    üretmez: aileye ait zincirler her onay kutusundan sessizce DÜŞER. Hata
    fırlamaz, sorgu çalışır, satır yoktur — teşhisi en zor kusur türü.
    """
    eksikler = sorted(
        uye.value for uye in ApprovalDocumentType if uye not in DOCUMENT_PROJECT_COLUMNS
    )

    assert not eksikler, (
        f"zincire giren ama kapsam eslemesi OLMAYAN aile(ler): {eksikler}. "
        "`visible_document_clause` bu aile icin hicbir dal uretmez ve zincirleri "
        "her onay kutusundan SESSIZCE duser — once evragin projesi cozulmelidir."
    )


def test_kapsam_kolonlarinin_HEPSI_NOT_NULL_dur():
    """Kapsam kolonu NULL olabiliyorsa süzgeç iki yüzeyi AYRIŞTIRIR.

    `visible_document_clause` `project_id IN (...)` yazar; SQL'de `NULL IN (...)`
    **hiçbir zaman doğru değildir**. Yani projesi NULL olan bir evrak onay
    kutusunda GÖRÜNMEZ. Kendi modülü onu "projesiz ⇒ modül izni olan herkese
    açık" sayıyorsa (fatura bunu yapar) aynı evrak iki yüzeyde iki farklı
    görünürlük kuralına tabi olur.

    🔴 Bugün üç ailenin üçünde de kolon NOT NULL'dur; test o hâlin bekçisidir.
    """
    nullable_olanlar = sorted(
        document_type.value
        for document_type, (_, project_column) in DOCUMENT_PROJECT_COLUMNS.items()
        if project_column.property.columns[0].nullable
    )

    assert not nullable_olanlar, (
        f"kapsam kolonu NULL olabilen aile(ler): {nullable_olanlar}. "
        "`project_id IS NULL` satir alt sorguyu KACIRIR: evrak onay kutusunda "
        "gorunmez ama kendi modulunde gorunur — ayni evrak icin IKI farkli "
        "gorunurluk kurali dogar."
    )


# --------------------------------------------------------------------------- #
# 2. BORDRO DÖNEMİ — ölçülen üç yapısal engel
# --------------------------------------------------------------------------- #


def test_BORDRO_DONEMI_hicbir_projeye_baglanamaz():
    """🔴 ÖLÇÜLDÜ: `payroll_periods`ta `project_id` de `site_id` de YOKTUR.

    Bu bir eksiklik değil, `payroll/service.py`de gerekçelendirilmiş bir ÜRÜN
    KARARIDIR: bordro şirket geneli bir İK varlığıdır ve kapsam denetimi
    `payroll` İZNİDİR, proje erişimi değil ("süzgeç konsaydı aynı ayın toplamı
    iki kullanıcıda iki farklı sayı gösterirdi").

    Sonucu OK-1B için bağlayıcıdır: bordro dönemi zincire girerse motorun
    DÖRDÜNCÜ bekçisinin (IDOR/proje kapsamı) dayanacağı bir kolon YOKTUR. Kolon
    sonradan eklenirse bu test kırılır ve karar YENİDEN verilmelidir.
    """
    kolonlar = set(PayrollPeriod.__table__.columns.keys())

    assert "project_id" not in kolonlar, (
        "`payroll_periods.project_id` ACILMIS — bordro artik proje kapsamli. "
        "Zincirin IDOR bekcisi bu kolona baglanabilir; OK-1B'nin 'kapsam "
        "cozulemiyor' gerekcesi ARTIK GECERSIZ, karar yeniden verilmeli."
    )
    assert "site_id" not in kolonlar, (
        "`payroll_periods.site_id` ACILMIS — kapsam artik santiyeden turetilebilir; "
        "OK-1B'nin kapsam gerekcesi yeniden degerlendirilmeli."
    )


def test_BORDRO_DONEMI_olusturani_SATIRDA_tasinmaz():
    """🔴 ÖLÇÜLDÜ: `payroll_periods`ta oluşturan kullanıcı kolonu YOKTUR.

    Zincir motorunun **5. bekçisi** ("kendi evrağını onaylayamazsın") zincirin
    `created_by_user_id` alanına bakar ve `create_chain` onu ZORUNLU parametre
    olarak ister. Bordro döneminde satırda taşınan TEK aktör `approved_by_id`dir
    ve o, zincir kurulduktan ÇOK SONRA yazılır.

    Üstelik dönemi `pending_approval`a taşıyan yollardan biri
    (`_promote_period_after_compute`) `compute_period` içindedir ve
    `compute_period` **aktör parametresi ALMAZ** — yani zincir orada açılacaksa
    yazılacak bir "oluşturan" da yoktur.
    """
    kolonlar = set(PayrollPeriod.__table__.columns.keys())

    # 🔴 BAYATLIK KANARYASI ÖNCE koşar. Sonra koşsaydı ve tablo tamamen
    # yeniden adlandırılsaydı, asıl iddia "kolon yok" diye BOŞUNA geçer
    # (vacuously true) ve ölçümün bayatladığını hiçbir şey söylemezdi.
    assert "approved_by_id" in kolonlar, (
        "`payroll_periods.approved_by_id` KAYBOLMUS — bordro doneminin tek aktor "
        "kolonu buydu; bu dosyadaki bordro olcumleri BAYATLAMIS olabilir."
    )
    assert "created_by_id" not in kolonlar and "created_by_user_id" not in kolonlar, (
        "`payroll_periods`a olusturan kolonu EKLENMIS — zincirin 5. bekcisi "
        "(kendi evragini onaylayamazsin) artik satirdan beslenebilir."
    )


def test_BORDRO_DONEMI_zinciri_TEK_YONLUDUR_ret_adimi_yoktur():
    """🔴 ÖLÇÜLDÜ: `PERIOD_TRANSITIONS` yalnız İLERİ üç çift taşır.

    Zincir motorunda **ret bir karardır** ve evrağı geriye alır (OK-1A K2: ret
    zinciri bitirir, `approval_chains` satırı silinir). Bordro döneminde geriye
    giden HİÇBİR çift yoktur; `pending_approval → draft` eklenmeden ret ucu
    bağlanamaz.

    🔴 VE EKLEMEK TEK SATIRLIK DEĞİLDİR: `next_period_step` hedefi bu tablodan
    TÜRETİR ve bir durumun birden çok ardılı olursa **`ValueError` fırlatır**
    ("Dönem zinciri artık doğrusal değil"). `pending_approval`a ikinci bir ardıl
    eklemek, o durumdaki HER onay çağrısını 500'e çevirir. Yani ret ucu açmak
    dönem durum makinesinin YENİDEN TASARIMINI ister.
    """
    geri_donenler = sorted(
        f"{kaynak.value} -> {hedef.value}"
        for kaynak, hedef in PERIOD_TRANSITIONS
        if _adim_sirasi(hedef) < _adim_sirasi(kaynak)
    )

    assert not geri_donenler, (
        f"bordro doneminde GERI donen gecis acilmis: {geri_donenler}. "
        "`next_period_step` ardil sayisi 1'den buyuk olunca ValueError firlatir — "
        "bu gecisle birlikte o fonksiyonun da yeniden tasarlandigi dogrulanmali."
    )


#: Dönem durumlarının İLERİ sırası — ELLE yazıldı (`PayrollPeriodStatus`
#: tanım sırasından İTHAL EDİLMEDİ; ithal edilseydi enum'da üye yeri değişince
#: test kendi ölçütünü de birlikte kaydırır ve hiçbir şey bekçilemezdi).
_ADIM_SIRASI = {"draft": 0, "pending_approval": 1, "approved": 2, "paid": 3}


def _adim_sirasi(durum) -> int:  # noqa: ANN001
    return _ADIM_SIRASI[durum.value]


def test_BORDRO_DONEMININ_ret_ucu_YOKTUR():
    """🔴 ÖLÇÜLDÜ: dönemde `/reject` ucu yok; ret YALNIZ SATIR düzeyindedir.

    Zincire girmek `approve` **ve** `reject` uçlarını ister (OK-1C ikamesi ikisine
    birden bağlanır). Bordro döneminde ret ucu açmak YENİ BİR YOLDUR ve
    yol/operasyon sayacını da (`test_YOL_ve_OPERASYON_sayisi_SABIT_kalir`)
    değiştirir — yani kapsam genişlemesidir, bağlama işi değil.
    """
    from app.main import app

    yollar = {
        (metot, rota.path)
        for rota in _api_rotalari(app.routes)
        for metot in rota.methods - {"HEAD", "OPTIONS"}
    }

    assert ("POST", "/payroll/periods/{period_id}/approve") in yollar, (
        "bordro doneminin onay ucu KAYBOLMUS — olcum bayatladi."
    )
    assert ("POST", "/payroll/periods/{period_id}/reject") not in yollar, (
        "bordro donemine ret ucu ACILMIS — OK-1B'nin 'ret ucu yok' gerekcesi "
        "artik gecersiz; yol/operasyon sayaci ve durum makinesi birlikte "
        "gozden gecirilmeli."
    )
    assert ("POST", "/payroll/lines/{line_id}/reject") in yollar, (
        "SATIR ret ucu kaybolmus — olcum bayatladi."
    )


# --------------------------------------------------------------------------- #
# 3. FATURA — kapsam kolonu var ama NULL olabilir
# --------------------------------------------------------------------------- #


def test_FATURANIN_projesi_NULL_OLABILIR():
    """🔴 ÖLÇÜLDÜ: `invoices.project_id` NULLABLE'dır (üç mevcut ailede DEĞİL).

    `invoicing/service.py` bunu bilinçli bir ürün kararı olarak taşır: projesi
    olmayan (şirket geneli) fatura, modül izni olan herkese görünür. Onay kutusu
    süzgeci ise ters yönde çalışır ve `NULL IN (...)` asla doğru olmadığı için o
    faturayı GİZLER.

    İki yüzeyin aynı evrak için farklı cevap vermesi OK-1B'nin karara bağlaması
    gereken noktadır; test bugünkü hâli sabitler ki karar sessizce kaymasın.
    """
    kolon = Invoice.__table__.columns["project_id"]

    assert kolon.nullable, (
        "`invoices.project_id` artik NOT NULL — fatura, mevcut uc ailenin kapsam "
        "desenine UYUYOR demektir ve OK-1B'nin 'nullable kapsam' gerekcesi dustu."
    )
