import uuid

from app.core.access import AccessLevel, Scope, can_delete, satisfies


def test_access_exports_pure_domain_without_fastapi():
    # access.py FastAPI/DB'ye bağımlı OLMAMALI — saf domain.
    import app.core.access as access_module

    with open(access_module.__file__, encoding="utf-8") as handle:
        text = handle.read()
    assert "fastapi" not in text.lower()
    assert "get_db" not in text


def test_level_ordering():
    assert satisfies(AccessLevel.admin, AccessLevel.full)
    assert satisfies(AccessLevel.approve, AccessLevel.approve)
    assert not satisfies(AccessLevel.view, AccessLevel.draft)


def test_scope_values():
    assert {s.value for s in Scope} == {"all", "own", "project", "finance", "stock", "limited"}


class _Rec:
    def __init__(self, created_by: uuid.UUID, is_draft: bool):
        self.created_by = created_by
        self.is_draft = is_draft


def test_can_delete_admin_always():
    rec = _Rec(uuid.uuid4(), is_draft=False)
    assert can_delete(uuid.uuid4(), AccessLevel.admin, rec) is True


def test_can_delete_draft_exception_only_for_owner():
    owner = uuid.uuid4()
    rec = _Rec(owner, is_draft=True)
    assert can_delete(owner, AccessLevel.draft, rec) is True
    assert can_delete(uuid.uuid4(), AccessLevel.draft, rec) is False


def test_permissions_module_has_no_function_level_domain_imports():
    # Döngü yapısal kırıldıysa require_permission gövdesinde artık girintili
    # (fonksiyon içi) "from app.modules.roles.repository import" OLMAMALI.
    import app.core.permissions as perm_module

    with open(perm_module.__file__, encoding="utf-8") as handle:
        body = handle.read()
    assert body.count("from app.core.deps import get_current_user") == 1  # modül seviyesinde, 1 kez
    assert "\n        from app.modules.roles.repository import get_permission" not in body
