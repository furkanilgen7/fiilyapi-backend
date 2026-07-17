import enum


class AccessLevel(str, enum.Enum):
    """Erişim seviyesi. Sıralıdır: none < view < draft < request < approve < full < admin.

    full silmeyi KAPSAMAZ — silme yalnızca admin seviyesindedir (spec §5.0).
    """

    none = "none"
    view = "view"
    draft = "draft"
    request = "request"
    approve = "approve"
    full = "full"
    admin = "admin"


class Scope(str, enum.Enum):
    """Veri kapsamı — aktörün modül içinde hangi kayıtları görebildiği."""

    all = "all"
    own = "own"
    project = "project"
    finance = "finance"
    stock = "stock"
    limited = "limited"


_LEVEL_ORDER: dict[AccessLevel, int] = {
    AccessLevel.none: 0,
    AccessLevel.view: 1,
    AccessLevel.draft: 2,
    AccessLevel.request: 3,
    AccessLevel.approve: 4,
    AccessLevel.full: 5,
    AccessLevel.admin: 6,
}


def satisfies(actual: AccessLevel, required: AccessLevel) -> bool:
    """actual seviyesi, required seviyesini karşılıyor mu?"""
    return _LEVEL_ORDER[actual] >= _LEVEL_ORDER[required]
