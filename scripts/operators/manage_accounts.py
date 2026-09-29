"""Deployment-operator-only, audited account role and suspension command.

Run with an explicit LAUNCHPAD_DATABASE_URL in a restricted operator environment.
This command is intentionally not mounted in the HTTP application.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.auth.staff import StaffManagementError, StaffManagementService
from app.shared.db.database import Database, MigrationCompatibilityError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit an operator account change")
    parser.add_argument("--actor", required=True, help="operator identity recorded in the audit")
    parser.add_argument("--account-id", required=True, type=UUID, help="target account UUID")
    commands = parser.add_subparsers(dest="command", required=True)
    set_role = commands.add_parser("set-role", help="grant or revoke a staff role")
    set_role.add_argument("--role", required=True, choices=("member", "reviewer", "admin"))
    commands.add_parser("suspend", help="suspend product changes")
    commands.add_parser("resume", help="resume product changes")
    return parser


async def _execute(arguments: argparse.Namespace, database_url: str) -> None:
    database = Database.connect(database_url)
    try:
        await database.ensure_compatible()
        sessions = async_sessionmaker(database.engine, expire_on_commit=False)
        manager = StaffManagementService()
        async with sessions() as session:
            if arguments.command == "set-role":
                await manager.set_role(
                    session,
                    target_account_id=arguments.account_id,
                    role=arguments.role,
                    actor=arguments.actor,
                )
            else:
                await manager.set_suspension(
                    session,
                    target_account_id=arguments.account_id,
                    suspended=arguments.command == "suspend",
                    actor=arguments.actor,
                )
    finally:
        await database.close()


def main(argv: Sequence[str] | None = None, environment: Mapping[str, str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    source = os.environ if environment is None else environment
    database_url = source.get("LAUNCHPAD_DATABASE_URL")
    if not database_url:
        print("LAUNCHPAD_DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        asyncio.run(_execute(arguments, database_url))
    except (StaffManagementError, MigrationCompatibilityError, SQLAlchemyError) as error:
        if isinstance(error, StaffManagementError):
            print(str(error), file=sys.stderr)
        else:
            print("operator change unavailable", file=sys.stderr)
        return 1
    except Exception:
        # Operator failures must not echo a connection URL or other secrets.
        print("operator change unavailable", file=sys.stderr)
        return 1
    print(f"account {arguments.account_id} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
