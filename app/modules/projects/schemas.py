import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.projects.models import ProjectStatus


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: ProjectStatus
    budget: Decimal
    progress_pct: Decimal
