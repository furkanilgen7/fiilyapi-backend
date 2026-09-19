import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import DROPPED_SCOPES, AccessLevel, Scope
from app.core.errors import DomainError, NotFoundError, PermissionLockedError
from app.modules.roles.models import SYSTEM_ADMIN_KEY, Module, Role, RolePermission
from app.modules.roles.repository import get_module, get_permission
from app.modules.roles.schemas import RoleCreate


async def update_role_permission(
    session: AsyncSession,
    role_id: uuid.UUID,
    module_key: str,
    level: AccessLevel,
    scope: Scope,
) -> RolePermission:
    """Matrisin bir hücresini günceller.

    system_admin rolünün hiçbir hücresi değiştirilemez — aktör kim olursa olsun.
    """
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")

    if role.key == SYSTEM_ADMIN_KEY:
        raise PermissionLockedError("Sistem Yöneticisi rolünün izinleri değiştirilemez")

    permission = await get_permission(session, role_id, module_key)
    if permission is None:
        # 🔴 Satırın YOKLUĞU "böyle bir hücre olamaz" demek DEĞİLDİR: uzantı
        # migration'ları izin satırlarını sabit `ROLE_ORDER` üzerinde yazar, o
        # yüzden migration'dan önce açılmış her özel rol sonradan inen modülün
        # hücresine sahip olmaz. Eskiden burada 404 atılıyordu ve yönetici o
        # modülü ekrandan KALICI OLARAK açamıyordu. Hücre artık burada doğar;
        # matris tarafı `repository.get_role_matrix` ile zaten görünür.
        # 404 YALNIZ modül gerçekten yoksa kalır — uydurma anahtar satır açmaz.
        module = await get_module(session, module_key)
        if module is None:
            raise NotFoundError("İzin satırı bulunamadı")
        permission = RolePermission(
            role_id=role_id,
            module_id=module.id,
            access_level=AccessLevel.none,
            scope=Scope.all,
        )
        session.add(permission)

    # 🔴 `Scope` DEKORATİFTİR: `app/core/permissions.py` içinde `scope` kelimesi
    # GEÇMEZ, hiçbir uç `permission.scope`u okumaz (`projects.service`in
    # `visible_projects`i yalnız `AccessLevel.admin` + `user_project_access`e
    # bakar). İzin Matrisi ekranı ise "Kendi / Sınırlı / Mali" etiketlerini
    # YAZIYLA vaat ediyor. Vaat uygulanana kadar YENİ bir daraltma yazılamaz:
    # 200 dönmek yöneticiye olmayan bir kısıtı kalıcı olarak onaylatırdı.
    # Seed satırları (roles/seed_data.py:183-227) AYNEN kalır — mevcut kapsam
    # geri gönderildiğinde seviye değişimi geçer, `all`a çekmek hep serbesttir.
    # 🔴 DÜŞEN kapsamlar MEVCUT OLSA BİLE geri yazılamaz (2026-09-19). Alttaki
    #    "mevcudu geri göndermek serbesttir" muafiyeti burada GEÇMEZ: geçseydi
    #    migration canlıyı temizledikten sonra bile uygulanmayan bir kapsam
    #    ekrandan YENİDEN doğabilirdi.
    if scope in DROPPED_SCOPES:
        raise PermissionLockedError(
            "Bu kapsam kaldırıldı; erişimi daraltmak için proje erişimini kullanın."
        )
    if scope is not Scope.all and scope != permission.scope:
        raise PermissionLockedError(
            "Kapsam kısıtı henüz uygulanmıyor; erişimi daraltmak için proje erişimini kullanın."
        )

    permission.access_level = level
    permission.scope = scope
    await session.flush()
    return permission


async def rename_role(
    session: AsyncSession,
    role_id: uuid.UUID,
    name: str,
    emoji: str,
    description: str,
) -> Role:
    """Rolün görünen bilgilerini günceller. key asla değişmez — kod ona dayanır."""
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    role.name = name
    role.emoji = emoji
    role.description = description
    await session.flush()
    return role


async def create_custom_role(session: AsyncSession, data: RoleCreate) -> Role:
    """Yeni özel rol oluşturur; tüm modüller için none/all izin satırı seedler."""
    existing = (
        await session.execute(select(Role).where(Role.key == data.key))
    ).scalar_one_or_none()
    if existing is not None:
        raise DomainError("Bu rol anahtarı zaten kullanılıyor")

    role = Role(
        key=data.key,
        name=data.name,
        emoji=data.emoji,
        description=data.description,
        is_system=False,
    )
    session.add(role)
    await session.flush()

    modules = (await session.execute(select(Module))).scalars().all()
    for module in modules:
        session.add(
            RolePermission(
                role_id=role.id,
                module_id=module.id,
                access_level=AccessLevel.none,
                scope=Scope.all,
            )
        )
    await session.flush()
    return role


async def delete_role(session: AsyncSession, role_id: uuid.UUID) -> None:
    """Özel rolü siler. Sistem rolleri kilitlidir."""
    role = (await session.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Rol bulunamadı")
    if role.is_system:
        raise PermissionLockedError("Sistem rolleri silinemez")

    from app.modules.users.models import User  # fonksiyon ici import (dongu riskini onler)

    in_use = (
        await session.execute(select(func.count()).select_from(User).where(User.role_id == role_id))
    ).scalar_one()
    if in_use > 0:
        raise DomainError("Bu role atanmış kullanıcılar var; önce onları başka role taşıyın")

    await session.delete(role)  # role_permissions CASCADE ile silinir
    await session.flush()
