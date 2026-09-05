"""`documents` modülünün eşleyici cephesi — BC-3'te paket oldu (TB-EQUIP emsali).

`core.py` BC-1'in üç tablosudur (klasör · künye · bayt), `links.py` BC-3'ün
varlık bağıdır (paylaşılan slot kataloğu + dört sahip-başına bağ tablosu).

🔴 Her sınıf BURADA **gerçekten içe aktarılır**, `__all__` yetmez: içe aktarılmayan
bir eşleyici `Base.metadata`ya kaydolmaz, `alembic autogenerate` tabloyu
"silinecek" diye raporlar ve `ForeignKey("documents.id")` gibi dize hedefler ilk
kullanımda `NoReferencedTableError` ile patlar (TB-EQUIP şema anlık görüntüsü
testinin gerekçesi). `alembic/env.py` ve `tests/conftest.py` yalnız bu cepheyi
import eder.
"""

from app.modules.documents.models.core import Document, DocumentBlob, DocumentFolder
from app.modules.documents.models.links import (
    ENTITY_DOCUMENT_SCOPE,
    EntityDocumentScope,
    EntityDocumentType,
    SectionDocument,
    SubcontractorContractDocument,
    UnitDocument,
    UnitSaleDocument,
)

__all__ = [
    "ENTITY_DOCUMENT_SCOPE",
    "Document",
    "DocumentBlob",
    "DocumentFolder",
    "EntityDocumentScope",
    "EntityDocumentType",
    "SectionDocument",
    "SubcontractorContractDocument",
    "UnitDocument",
    "UnitSaleDocument",
]
