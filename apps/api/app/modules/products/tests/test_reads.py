"""Private owner read projections never reveal another founder's draft or labels."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.modules.auth.models import Account
from app.modules.auth.staff import AuthAccessService
from app.modules.products.models import Product, ProductAsset, ProductTopic, Topic
from app.modules.products.policies import ProductNotFoundError
from app.modules.products.service import ProductService
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires check PostgreSQL")
def test_owner_reads_keep_private_topic_labels_scoped() -> None:
    async def verify() -> None:
        database = Database.connect(os.environ["DATABASE_URL"])
        founder_ids = (uuid4(), uuid4())
        product_ids = (uuid4(), uuid4())
        newest_id = uuid4()
        topic_id = uuid4()
        asset_ids = (UUID(int=1), UUID(int=2))
        topic_name = f"AI Tools {topic_id.hex[:8]}"
        now = datetime.now(UTC)
        service = ProductService(
            member_access=AuthAccessService(),
            payload_codec=EmailPayloadCodec({"reads-test": b"r" * 32}, "reads-test"),
        )
        try:
            await database.ensure_compatible()
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session, session.begin():
                for founder_id in founder_ids:
                    session.add(
                        Account(
                            id=founder_id,
                            email_display=f"{founder_id}@example.test",
                            email_key=f"{founder_id}@example.test",
                            password_hash="integration-only-placeholder",
                            created_at=now,
                            updated_at=now,
                        )
                    )
            async with sessions() as session, session.begin():
                await session.execute(
                    insert(Product).values(
                        [
                            {
                                "id": product_id,
                                "founder_id": founder_id,
                                "status": "draft",
                                "version": 1,
                                "name": "Private draft",
                                "created_at": now,
                                "updated_at": now,
                            }
                            for founder_id, product_id in zip(founder_ids, product_ids, strict=True)
                        ]
                    ),
                )
                await session.execute(
                    insert(Product).values(
                        id=newest_id,
                        founder_id=founder_ids[0],
                        status="draft",
                        version=0,
                        created_at=now,
                        updated_at=now + timedelta(minutes=1),
                    )
                )
                session.add(
                    Topic(id=topic_id, display_name=topic_name, name_key=topic_name.casefold())
                )
                await session.flush()
                session.add_all(
                    [
                        ProductTopic(
                            product_id=product_ids[0],
                            topic_id=topic_id,
                            position=1,
                            selected_label=topic_name,
                        ),
                        ProductTopic(
                            product_id=product_ids[1],
                            topic_id=topic_id,
                            position=1,
                            selected_label=topic_name.upper(),
                        ),
                    ]
                )
                session.add_all(
                    ProductAsset(
                        id=asset_id,
                        product_id=product_ids[0],
                        kind="screenshot",
                        state="clean",
                        staging_key=f"products/{founder_ids[0]}/{product_ids[0]}/{asset_id}-stage",
                        clean_key=f"products/{founder_ids[0]}/{product_ids[0]}/{asset_id}-clean",
                        media_type="image/png",
                        byte_count=100,
                        position=position,
                        expires_at=None,
                        attached_at=now,
                    )
                    for asset_id, position in zip(asset_ids, (2, 1), strict=True)
                )
            async with sessions() as session:
                first = await service.owner_detail(
                    session, actor_id=founder_ids[0], product_id=product_ids[0]
                )
                second = await service.owner_detail(
                    session, actor_id=founder_ids[1], product_id=product_ids[1]
                )
                own_page = await service.owner_list(session, actor_id=founder_ids[0], first=1)
                assert [topic.display_name for topic in first.topics] == [topic_name]
                assert [asset.id for asset in first.assets] == [asset_ids[1], asset_ids[0]]
                assert [topic.display_name for topic in second.topics] == [topic_name.upper()]
                assert [item.id for item in own_page.items] == [newest_id]
                assert own_page.next_cursor is not None
                next_page = await service.owner_list(
                    session, actor_id=founder_ids[0], first=1, after=own_page.next_cursor
                )
                assert [item.id for item in next_page.items] == [product_ids[0]]
                assert next_page.next_cursor is None
                choices = await service.topic_choices(session, actor_id=founder_ids[0])
                assert [(choice.topic_id, choice.display_name) for choice in choices] == [
                    (topic_id, topic_name)
                ]
                other_choices = await service.topic_choices(session, actor_id=founder_ids[1])
                assert [choice.display_name for choice in other_choices] == [topic_name.upper()]
                with pytest.raises(ProductNotFoundError):
                    await service.owner_detail(
                        session, actor_id=founder_ids[0], product_id=product_ids[1]
                    )
            async with sessions() as session, session.begin():
                topic = await session.get(Topic, topic_id)
                assert topic is not None
                topic.first_launched_at = now
            async with sessions() as session:
                launched = await service.topic_choices(session, actor_id=founder_ids[1])
                assert [(choice.topic_id, choice.display_name) for choice in launched] == [
                    (topic_id, topic_name)
                ]
        finally:
            async with database.engine.begin() as connection:
                await connection.execute(
                    delete(Product).where(Product.id.in_((*product_ids, newest_id)))
                )
                await connection.execute(delete(Topic).where(Topic.id == topic_id))
                await connection.execute(delete(Account).where(Account.id.in_(founder_ids)))
            await database.close()

    asyncio.run(verify())
