"""`GET /ai/tools` ve `GET /ai/context` yanıt şemaları (AI-0b T6).

Bu iki uç **akış içermez, model çağırmaz, panel beslemez**. `GET /ai/tools`
aynı zamanda **canlı doğrulama aracıdır**: iki farklı rolle çağrılıp listelerin
FARKLI geldiği ölçülür.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class AiToolRead(BaseModel):
    """Aktörün görebildiği bir araç. 🔴 `ucler` ve `kapilar` YAYINLANMAZ.

    Uç listesi bir iç uygulama detayıdır; yayınlamak istemciye "şu yolu çağır"
    fikri verirdi ve `navigate_to`nun kapalı-enum kararını (S22) dolanırdı.
    """

    ad: str
    aciklama: str
    kapsam: str
    kume: str


class AiToolListResponse(BaseModel):
    items: list[AiToolRead]
    total: int


class AiContextResponse(BaseModel):
    """S14'ün korkuluğu: AI sınırını **bilerek** çağırsın.

    `/auth/me` kapsam taşımaz; AI sınırını bilmeden çağırır ve 404'ü yalana
    çevirir. Bu uç `permissions` + görünür araç sicili + yetki dışı modülleri
    birlikte verir.
    """

    user_id: uuid.UUID
    role_key: str
    permissions: dict[str, str]
    #: Aktörün görebildiği araç adları — prompt'un ürettiğiyle AYNI küme (B8).
    arac_adlari: list[str]
    #: 🔴 Yetkisi olmadığı için düşen modüller ADIYLA (S9-c).
    yetkisiz_moduller: list[str]
    #: 🔴 `visible_project_ids` bu dilimde **YOKTUR**: onu üretmek
    #: `projects.repository`yi çağırmayı gerektirirdi ve bu uç `ai` modülünün
    #: kapısıyla korunuyor, `projects`ınkiyle değil — yani `projects:none` olan
    #: bir rol proje kimliklerini buradan sızdırabilirdi. Kullanıcı proje
    #: kümesini `projeleri_listele` aracıyla, kendi kapısından geçerek öğrenir.
    proje_kimlikleri_notu: str
