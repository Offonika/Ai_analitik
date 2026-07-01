#!/usr/bin/env python3
"""Manage Shumeyko web cabinet users from the server side."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument("--tenant-id", default="shumeyko")
    parser.add_argument("--actor-email", default="")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List users visible to the actor admin.")

    create = subparsers.add_parser("create", help="Create a user.")
    create.add_argument("--email", required=True)
    create.add_argument("--name", default="")
    create.add_argument("--role", required=True, choices=sorted(repository.VALID_ROLES))
    create.add_argument("--password-env", default="")
    create.add_argument("--password-file", type=Path, default=None)
    create.add_argument("--show-password", action="store_true")

    reset = subparsers.add_parser("reset-password", help="Reset user password.")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-file", type=Path, default=None)
    reset.add_argument("--show-password", action="store_true")

    disable = subparsers.add_parser("disable", help="Disable a user.")
    disable.add_argument("--email", required=True)

    enable = subparsers.add_parser("enable", help="Enable a user.")
    enable.add_argument("--email", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = args.database_url or "sqlite:///data/web/shumeyko_web.sqlite3"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        actor = _actor(db, args.actor_email)
        if args.command == "list":
            for user in repository.list_users_for_admin(db, actor):
                access = ", ".join(
                    f"{item.tenant_id}:{item.role}" for item in user.access
                )
                state = "active" if user.is_active else "disabled"
                print(f"{user.email}\t{state}\t{access}")
            return 0
        if args.command == "create":
            password = _password_from_env(args.password_env)
            generated = False
            if not password:
                password = security.new_temporary_password()
                generated = True
            user = repository.create_managed_user(
                db,
                admin=actor,
                email=args.email,
                name=args.name,
                tenant_id=args.tenant_id,
                role=args.role,
                password=password,
            )
            db.commit()
            _persist_password(args.password_file, user.email, password, generated)
            _print_password(args.show_password, password, generated)
            print(f"created {user.email} ({args.role})")
            return 0
        target = _user_by_email(db, args.email)
        if args.command == "reset-password":
            password = security.new_temporary_password()
            repository.reset_managed_user_password(
                db,
                admin=actor,
                target_user_id=target.id,
                tenant_id=args.tenant_id,
                password=password,
            )
            db.commit()
            _persist_password(args.password_file, target.email, password, True)
            _print_password(args.show_password, password, True)
            print(f"reset {target.email}")
            return 0
        if args.command in {"disable", "enable"}:
            repository.update_managed_user(
                db,
                admin=actor,
                target_user_id=target.id,
                tenant_id=args.tenant_id,
                is_active=args.command == "enable",
            )
            db.commit()
            print(f"{args.command}d {target.email}")
            return 0
    return 0


def _actor(db, actor_email: str) -> User:
    if actor_email:
        user = _user_by_email(db, actor_email)
    else:
        admins = [
            user
            for user in db.query(User).order_by(User.email).all()
            if repository.has_role(user, {"admin"})
        ]
        if not admins:
            raise SystemExit("No admin user found. Import/bootstrap first.")
        user = admins[0]
    if not user.is_active or not repository.has_role(user, {"admin"}):
        raise SystemExit("Actor must be an active admin.")
    return user


def _user_by_email(db, email: str) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()
    if user is None:
        raise SystemExit(f"User not found: {email}")
    return user


def _password_from_env(name: str) -> str:
    if not name:
        return ""
    value = os.getenv(name, "")
    if not value:
        raise SystemExit(f"Set {name} before using it as password source.")
    return value


def _persist_password(
    output_path: Path | None, email: str, password: str, generated: bool
) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{email}\t{password}\t{'generated' if generated else 'provided'}\n"
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    output_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _print_password(show_password: bool, password: str, generated: bool) -> None:
    if show_password:
        print(f"temporary password: {password}")
    elif generated:
        print("temporary password generated; use --show-password or --password-file")


if __name__ == "__main__":
    raise SystemExit(main())
