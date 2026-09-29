"""Operator-only account changes and self-visible authorization state."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.main import create_app
from app.modules.auth.models import Account, AccountAdminAction
from app.modules.auth.staff import AuthAccessService, StaffManagementError, StaffManagementService
from app.modules.products.models import Product, ProductSubmission
from app.shared.db.database import Database
from app.shared.security.passwords import hash_password
from conftest import IntegrationSettings
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_login_and_session_show_live_self_role_and_suspension(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    account_id = uuid4()
    credentials = {"email": "self-state@example.com", "password": "a secure password!"}

    async def prepare() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            await database.prepare()
            now = datetime.now(UTC)
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display=credentials["email"],
                        email_key=credentials["email"],
                        password_hash=hash_password(credentials["password"]),
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
        finally:
            await database.close()

    async def change_account(account_id: UUID) -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            async with database.engine.begin() as connection:
                await connection.execute(
                    update(Account)
                    .where(Account.id == account_id)
                    .values(role="reviewer", suspended_at=datetime.now(UTC))
                )
        finally:
            await database.close()

    asyncio.run(prepare())
    origin = {"Origin": "http://localhost:8080"}
    with TestClient(create_app()) as client:
        login = client.post("/api/v1/auth/login", json=credentials, headers=origin)
        assert login.status_code == 200
        assert login.json()["role"] == "member"
        assert login.json()["suspended"] is False
        assert login.json()["csrf_token"]
        assert UUID(login.json()["account_id"]) == account_id
        session_cookie = login.cookies["__Host-launchpad_session"]
        asyncio.run(change_account(account_id))
        current = client.get(
            "/api/v1/auth/session",
            cookies={"__Host-launchpad_session": session_cookie},
        )
        assert current.status_code == 200
        assert current.json()["role"] == "reviewer"
        assert current.json()["suspended"] is True
        assert current.json()["account_id"] == str(account_id)
        assert current.json()["csrf_token"] == login.json()["csrf_token"]
        changed_login = client.post("/api/v1/auth/login", json=credentials, headers=origin)
        assert changed_login.status_code == 200
        assert changed_login.json()["role"] == "reviewer"
        assert changed_login.json()["suspended"] is True


def test_role_grants_and_revocation_write_actor_and_before_after_audit(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id = uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display="staff-target@example.com",
                        email_key="staff-target@example.com",
                        password_hash="not-used",
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            manager = StaffManagementService()
            async with sessions() as session:
                assert (
                    await manager.set_role(
                        session,
                        target_account_id=account_id,
                        role="reviewer",
                        actor="ops.deploy",
                    )
                ).role == "reviewer"
                assert (
                    await manager.set_role(
                        session,
                        target_account_id=account_id,
                        role="admin",
                        actor="ops.deploy",
                    )
                ).role == "admin"
                assert (
                    await manager.set_role(
                        session,
                        target_account_id=account_id,
                        role="member",
                        actor="ops.deploy",
                    )
                ).role == "member"
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.role == "member"
                actions = (
                    await session.scalars(
                        select(AccountAdminAction)
                        .where(AccountAdminAction.target_account_id == account_id)
                        .order_by(AccountAdminAction.created_at, AccountAdminAction.id)
                    )
                ).all()
                assert len(actions) == 3
                assert [action.actor for action in actions] == ["ops.deploy"] * 3
                assert [action.action for action in actions] == ["set_role"] * 3
                assert [json.loads(action.before_state)["role"] for action in actions] == [
                    "member",
                    "reviewer",
                    "admin",
                ]
                assert [json.loads(action.after_state)["role"] for action in actions] == [
                    "reviewer",
                    "admin",
                    "member",
                ]
                assert all("password" not in action.before_state for action in actions)
        finally:
            await database.close()

    asyncio.run(verify())


def test_suspension_and_resumption_are_audited_without_hiding_pending_work(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id, product_id = uuid4(), uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display="founder@example.com",
                        email_key="founder@example.com",
                        password_hash="not-used",
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(Product).values(
                        id=product_id,
                        founder_id=account_id,
                        status="submitted",
                        name="Pending product",
                        pitch="Ready for review",
                        description="Private details",
                        website_url="https://example.com",
                        website_key="https://example.com",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(ProductSubmission).values(
                        id=uuid4(),
                        product_id=product_id,
                        state="pending",
                        submitted_at=now,
                        product_version=0,
                    )
                )
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            manager = StaffManagementService()
            async with sessions() as session:
                state = await manager.set_suspension(
                    session,
                    target_account_id=account_id,
                    suspended=True,
                    actor="ops.deploy",
                )
                assert state.suspended_at is not None
            async with sessions() as session:
                flags = await AuthAccessService().founder_states(session, [account_id])
                assert flags[account_id].suspended_at is not None
                pending = await session.scalar(
                    select(ProductSubmission).where(ProductSubmission.product_id == product_id)
                )
                assert pending is not None and pending.state == "pending"
            async with sessions() as session:
                state = await manager.set_suspension(
                    session,
                    target_account_id=account_id,
                    suspended=False,
                    actor="ops.deploy",
                )
                assert state.suspended_at is None
            async with sessions() as session:
                actions = (
                    await session.scalars(
                        select(AccountAdminAction)
                        .where(AccountAdminAction.target_account_id == account_id)
                        .order_by(AccountAdminAction.created_at, AccountAdminAction.id)
                    )
                ).all()
                assert [action.action for action in actions] == ["suspend", "resume"]
                assert json.loads(actions[0].before_state)["suspended_at"] is None
                assert json.loads(actions[0].after_state)["suspended_at"] is not None
                assert json.loads(actions[1].after_state)["suspended_at"] is None
        finally:
            await database.close()

    asyncio.run(verify())


def test_unverified_staff_grant_changes_nothing(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id = uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display="unverified@example.com",
                        email_key="unverified@example.com",
                        password_hash="not-used",
                        created_at=now,
                        updated_at=now,
                    )
                )
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session:
                with pytest.raises(StaffManagementError, match="must be verified"):
                    await StaffManagementService().set_role(
                        session,
                        target_account_id=account_id,
                        role="reviewer",
                        actor="ops.deploy",
                    )
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.role == "member"
                assert (await session.scalar(select(func.count(AccountAdminAction.id)))) == 0
        finally:
            await database.close()

    asyncio.run(verify())


def test_failed_audit_insert_rolls_back_role_change(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    async def verify() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        account_id = uuid4()
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display="audit-failure@example.com",
                        email_key="audit-failure@example.com",
                        password_hash="not-used",
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    text(
                        "CREATE FUNCTION reject_admin_audit() RETURNS trigger "
                        "LANGUAGE plpgsql AS $$ BEGIN "
                        "RAISE EXCEPTION 'audit unavailable'; END $$"
                    )
                )
                await connection.execute(
                    text(
                        "CREATE TRIGGER reject_admin_audit_insert "
                        "BEFORE INSERT ON account_admin_actions "
                        "FOR EACH ROW EXECUTE FUNCTION reject_admin_audit()"
                    )
                )
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session:
                with pytest.raises(DBAPIError):
                    await StaffManagementService().set_role(
                        session,
                        target_account_id=account_id,
                        role="reviewer",
                        actor="ops.deploy",
                    )
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.role == "member"
                assert await session.scalar(select(func.count(AccountAdminAction.id))) == 0
        finally:
            await database.close()

    asyncio.run(verify())


def test_restricted_operator_command_handles_role_and_suspension_with_audit(
    integration_settings_fixture: IntegrationSettings, reset_database: None
) -> None:
    account_id = uuid4()

    async def seed() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        now = datetime.now(UTC)
        try:
            await database.prepare()
            async with database.engine.begin() as connection:
                await connection.execute(
                    insert(Account).values(
                        id=account_id,
                        email_display="operator-target@example.com",
                        email_key="operator-target@example.com",
                        password_hash="not-used",
                        verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
        finally:
            await database.close()

    async def inspect_change() -> None:
        database = Database.connect(integration_settings_fixture.database_url)
        try:
            sessions = async_sessionmaker(database.engine, expire_on_commit=False)
            async with sessions() as session:
                account = await session.get(Account, account_id)
                assert account is not None and account.role == "member"
                assert account.suspended_at is None
                actions = (
                    await session.scalars(
                        select(AccountAdminAction)
                        .where(AccountAdminAction.target_account_id == account_id)
                        .order_by(AccountAdminAction.created_at, AccountAdminAction.id)
                    )
                ).all()
                assert [action.action for action in actions] == [
                    "set_role",
                    "suspend",
                    "resume",
                    "set_role",
                ]
                assert all(action.actor == "ops.deploy" for action in actions)
        finally:
            await database.close()

    asyncio.run(seed())
    environment = dict(os.environ)
    environment["LAUNCHPAD_DATABASE_URL"] = integration_settings_fixture.database_url
    for command in (
        ["set-role", "--role", "reviewer"],
        ["suspend"],
        ["resume"],
        ["set-role", "--role", "member"],
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(Path("scripts/operators/manage_accounts.py")),
                "--actor",
                "ops.deploy",
                "--account-id",
                str(account_id),
                *command,
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"account {account_id} updated"
        assert "operator-target@example.com" not in result.stdout
    asyncio.run(inspect_change())


def test_browser_has_no_staff_mutation_route() -> None:
    with TestClient(create_app()) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert all(
            "staff" not in path and "role" not in path and "suspend" not in path
            for path in paths
            if path.startswith("/api/v1/auth/")
        )
        assert client.post("/api/v1/auth/staff", json={}).status_code == 404


def test_operator_command_requires_explicit_database_target() -> None:
    environment = dict(os.environ)
    environment.pop("LAUNCHPAD_DATABASE_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/operators/manage_accounts.py")),
            "--actor",
            "ops.deploy",
            "--account-id",
            str(uuid4()),
            "suspend",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "LAUNCHPAD_DATABASE_URL is required"


def test_operator_command_hides_invalid_connection_details() -> None:
    environment = dict(os.environ)
    environment["LAUNCHPAD_DATABASE_URL"] = "invalid-url-with-secret-marker"
    result = subprocess.run(
        [
            sys.executable,
            str(Path("scripts/operators/manage_accounts.py")),
            "--actor",
            "ops.deploy",
            "--account-id",
            str(uuid4()),
            "suspend",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=10,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "operator change unavailable"
    assert "secret-marker" not in result.stderr
