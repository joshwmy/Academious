"""Thin application-owned boundary around FastAPI Users (ADR 0005)."""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from email.message import EmailMessage
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from academious.core.config import get_settings
from academious.db.models import AccessToken, User


class UserRead(schemas.BaseUser[uuid.UUID]):
    display_name: str
    recommendation_data_consent: bool
    consent_version: str | None
    consented_at: datetime | None


class UserCreate(schemas.BaseUserCreate):
    display_name: str = Field(min_length=1, max_length=120)
    recommendation_data_consent: Literal[True]


class UserUpdate(schemas.BaseUserUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


@lru_cache(maxsize=1)
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_async_sessionmaker()() as session:
        yield session


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> AsyncGenerator[SQLAlchemyUserDatabase[User, uuid.UUID], None]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_access_token_db(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase[Any], None]:
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_settings().auth_secret
    verification_token_secret = get_settings().auth_secret

    async def validate_password(self, password: str, user: Any) -> None:
        await super().validate_password(password, user)
        if len(password) < 12:
            from fastapi_users import exceptions

            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least 12 characters."
            )

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        settings = get_settings()
        await self.user_db.update(
            user,
            {
                "recommendation_data_consent": True,
                "consent_version": settings.recommendation_consent_version,
                "consented_at": datetime.now(UTC),
            },
        )

    async def on_after_request_verify(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        settings = get_settings()
        if not settings.smtp_host or not settings.smtp_from:
            return
        verify_url = f"{settings.frontend_url.rstrip('/')}/verify?token={token}"
        await asyncio.to_thread(
            _send_email,
            user.email,
            "Verify your Academious account",
            "Verify your Academious account to sync recommendations:",
            verify_url,
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        settings = get_settings()
        if not settings.smtp_host or not settings.smtp_from:
            return
        reset_url = f"{settings.frontend_url.rstrip('/')}/account?reset_token={token}"
        await asyncio.to_thread(
            _send_email,
            user.email,
            "Reset your Academious password",
            "Use this link to choose a new Academious password:",
            reset_url,
        )


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase[User, uuid.UUID], Depends(get_user_db)],
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


def get_database_strategy(
    database: Annotated[SQLAlchemyAccessTokenDatabase[Any], Depends(get_access_token_db)],
) -> DatabaseStrategy[User, uuid.UUID, Any]:
    return DatabaseStrategy(database, lifetime_seconds=get_settings().auth_session_seconds)


_settings = get_settings()
cookie_transport = CookieTransport(
    cookie_name="academious_session",
    cookie_max_age=_settings.auth_session_seconds,
    cookie_secure=_settings.auth_cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)
auth_backend = AuthenticationBackend(
    name="session",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_verified_user = fastapi_users.current_user(active=True, verified=True)
current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(optional=True, active=True)


def _send_email(recipient: str, subject: str, introduction: str, action_url: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(f"{introduction}\n\n{action_url}\n\nThis link expires automatically.")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
