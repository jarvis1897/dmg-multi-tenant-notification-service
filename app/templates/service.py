from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import ConflictError, NotFoundError
from app.templates.models import Template
from app.templates.schemas import TemplateCreate, TemplateUpdate


class TemplateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, tenant_id: str, data: TemplateCreate, created_by: str) -> Template:
        conflict = await self.db.execute(
            select(Template).where(
                Template.tenant_id == tenant_id,
                Template.name == data.name,
                Template.channel == data.channel.value,
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise ConflictError("A template with this name already exists for this channel")

        template = Template(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            channel=data.channel.value,
            subject=data.subject,
            body=data.body,
            variables=data.variables,
            created_by=created_by,
        )
        self.db.add(template)
        await self.db.flush()
        return template

    async def get_by_id(self, tenant_id: str, template_id: str) -> Template:
        result = await self.db.execute(
            select(Template).where(Template.id == template_id, Template.tenant_id == tenant_id)
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise NotFoundError(f"Template '{template_id}' not found")
        return template

    async def list_all(self, tenant_id: str) -> list[Template]:
        result = await self.db.execute(
            select(Template).where(Template.tenant_id == tenant_id).order_by(Template.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(self, tenant_id: str, template_id: str, data: TemplateUpdate) -> Template:
        template = await self.get_by_id(tenant_id, template_id)
        update_data = data.model_dump(exclude_none=True)

        new_name = update_data.get("name")
        if new_name and new_name != template.name:
            conflict = await self.db.execute(
                select(Template).where(
                    Template.tenant_id == tenant_id,
                    Template.name == new_name,
                    Template.channel == template.channel,
                    Template.id != template_id,
                )
            )
            if conflict.scalar_one_or_none() is not None:
                raise ConflictError("A template with this name already exists for this channel")

        for field, value in update_data.items():
            setattr(template, field, value)
        await self.db.flush()
        return template

    async def delete(self, tenant_id: str, template_id: str) -> None:
        template = await self.get_by_id(tenant_id, template_id)
        await self.db.delete(template)
        await self.db.flush()
