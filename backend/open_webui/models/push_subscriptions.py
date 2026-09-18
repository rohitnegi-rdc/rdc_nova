import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Text, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

####################
# Push Subscription DB Schema
####################


class PushSubscription(Base):
    __tablename__ = 'push_subscription'

    id = Column(Text, primary_key=True, unique=True)
    user_id = Column(Text, nullable=False)

    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)

    user_agent = Column(Text, nullable=True)

    created_at = Column(BigInteger)
    last_used_at = Column(BigInteger)


class PushSubscriptionModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str

    endpoint: str
    p256dh: str
    auth: str

    user_agent: Optional[str] = None

    created_at: int
    last_used_at: int


class PushSubscriptionTable:
    async def upsert_by_endpoint(
        self,
        user_id: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> PushSubscriptionModel:
        async with get_async_db_context(db) as db:
            now = int(time.time_ns())

            result = await db.execute(select(PushSubscription).filter(PushSubscription.endpoint == endpoint))
            subscription = result.scalars().first()

            if subscription:
                subscription.user_id = user_id
                subscription.p256dh = p256dh
                subscription.auth = auth
                subscription.user_agent = user_agent
                subscription.last_used_at = now
            else:
                subscription = PushSubscription(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    endpoint=endpoint,
                    p256dh=p256dh,
                    auth=auth,
                    user_agent=user_agent,
                    created_at=now,
                    last_used_at=now,
                )
                db.add(subscription)

            await db.commit()
            await db.refresh(subscription)
            return PushSubscriptionModel.model_validate(subscription)

    async def get_by_user_id(
        self, user_id: str, db: Optional[AsyncSession] = None
    ) -> list[PushSubscriptionModel]:
        async with get_async_db_context(db) as db:
            result = await db.execute(select(PushSubscription).filter(PushSubscription.user_id == user_id))
            return [PushSubscriptionModel.model_validate(s) for s in result.scalars().all()]

    async def delete_by_endpoint(self, endpoint: str, db: Optional[AsyncSession] = None) -> bool:
        async with get_async_db_context(db) as db:
            await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
            await db.commit()
            return True


PushSubscriptions = PushSubscriptionTable()
