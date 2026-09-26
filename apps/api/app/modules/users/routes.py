"""Thin REST transport for private profile actions and gated photos."""

import base64
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from graphql import GraphQLError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from app.modules.auth.sessions import MemberContext, SessionService, UnauthenticatedError
from app.modules.users.graphql import build_router, validate_read_query
from app.modules.users.policies import (
    ProfileConflictError,
    ProfileForbiddenError,
    ProfileInfrastructureError,
    ProfileValidationError,
)
from app.modules.users.schemas import (
    PhotoCompleteResponse,
    PhotoUploadRequest,
    PhotoUploadResponse,
    ProfilePatchRequest,
    ProfileResponse,
)
from app.modules.users.service import MemberIdentity, ProfileResult, ProfileService
from app.shared.config.settings import Settings
from app.shared.db.database import Database
from app.shared.email.codec import EmailPayloadCodec
from app.shared.events.outbox import OutboxRepository
from app.shared.security.csrf import RequestSecurityError, require_csrf, validate_origin
from app.shared.storage.objects import (
    CleanPhoto,
    ObjectNotFound,
    ObjectOperationError,
    ObjectValidationError,
    PrivateObjectStore,
)


class _BoundMemberAccess:
    def __init__(self, member: MemberContext | None) -> None:
        self.member = member

    async def get_member(
        self, session: AsyncSession, account_id: UUID, *, lock: bool = False
    ) -> MemberIdentity | None:
        if self.member is None or self.member.account_id != account_id:
            return None
        return MemberIdentity(account_id, self.member.email_display, self.member.verified)


def router(
    *, settings: Settings, database: Database, redis: Redis, storage: PrivateObjectStore
) -> tuple[APIRouter, APIRouter]:
    if settings.outbox_key is None or settings.outbox_key_id is None:
        raise RuntimeError("Outbox encryption configuration is required.")
    if settings.mail_web_origin is None:
        raise RuntimeError("Mail web origin configuration is required.")
    codec = EmailPayloadCodec(
        {settings.outbox_key_id: base64.b64decode(settings.outbox_key.get_secret_value())},
        settings.outbox_key_id,
    )
    session_service = SessionService()
    session_factory = async_sessionmaker(database.engine, expire_on_commit=False)
    routes = APIRouter(prefix="/api/v1")

    async def db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    DbSession = Annotated[AsyncSession, Depends(db_session)]

    async def current_member(request: Request, session: AsyncSession) -> MemberContext:
        secret = request.cookies.get(settings.session_cookie_name)
        if not secret:
            raise HTTPException(status_code=401, detail="authentication required")
        try:
            return await session_service.resolve(session, session_secret=secret)
        except UnauthenticatedError as error:
            raise HTTPException(status_code=401, detail="authentication required") from error

    def service_for(member: MemberContext | None) -> ProfileService:
        return ProfileService(
            member_access=_BoundMemberAccess(member),
            outbox_repository=OutboxRepository(),
            payload_codec=codec,
            mail_web_origin=str(settings.mail_web_origin),
        )

    def check_origin(request: Request) -> None:
        try:
            validate_origin(request.headers.get("origin"), settings.trusted_web_origins)
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error

    def check_csrf(request: Request, member: MemberContext, token: str | None) -> None:
        try:
            require_csrf(
                origin=request.headers.get("origin"),
                trusted_origin=settings.trusted_web_origins,
                token=token,
                expected_digest=member.csrf_digest,
            )
        except RequestSecurityError as error:
            raise HTTPException(status_code=403, detail="request rejected") from error

    def map_profile_error(error: Exception) -> HTTPException:
        if isinstance(error, ProfileForbiddenError):
            return HTTPException(status_code=403, detail="profile access is forbidden")
        if isinstance(error, ProfileConflictError):
            return HTTPException(status_code=409, detail="profile changed; reload and retry")
        if isinstance(error, ProfileValidationError):
            return HTTPException(status_code=422, detail="invalid profile")
        if isinstance(error, ProfileInfrastructureError):
            return HTTPException(status_code=503, detail="service unavailable")
        if isinstance(error, SQLAlchemyError | RedisError):
            return HTTPException(status_code=503, detail="service unavailable")
        return HTTPException(status_code=400, detail="request could not be completed")

    @routes.patch("/me/profile", response_model=ProfileResponse)
    async def update_profile(
        payload: ProfilePatchRequest,
        request: Request,
        response: Response,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProfileResponse:
        check_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            check_csrf(request, member, x_csrf_token)
            service = service_for(member)
            values: dict[str, Any] = {"expected_version": payload.version}
            for field in ("display_name", "bio", "links"):
                if field in payload.model_fields_set:
                    values[field] = getattr(payload, field)
            if "photo_upload_id" in payload.model_fields_set:
                values["photo_key"] = (
                    None
                    if payload.photo_upload_id is None
                    else await service.resolve_photo_upload(
                        session, actor_id=member.account_id, upload_id=payload.photo_upload_id
                    )
                )
            try:
                result = await service.update_profile(session, actor_id=member.account_id, **values)
            except (
                ProfileForbiddenError,
                ProfileConflictError,
                ProfileValidationError,
                ProfileInfrastructureError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_profile_error(error) from error
        response.headers["Cache-Control"] = "no-store"
        return _response(result, became_private=result.became_private)

    @routes.post("/me/profile/publish", response_model=ProfileResponse)
    async def publish_profile(
        payload: ProfilePatchRequest,
        request: Request,
        response: Response,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProfileResponse:
        check_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            check_csrf(request, member, x_csrf_token)
            try:
                result = await service_for(member).publish(
                    session, actor_id=member.account_id, expected_version=payload.version
                )
            except (
                ProfileForbiddenError,
                ProfileConflictError,
                ProfileValidationError,
                ProfileInfrastructureError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_profile_error(error) from error
        response.headers["Cache-Control"] = "no-store"
        return _response(result)

    @routes.post("/me/profile/unpublish", response_model=ProfileResponse)
    async def unpublish_profile(
        payload: ProfilePatchRequest,
        request: Request,
        response: Response,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> ProfileResponse:
        check_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            check_csrf(request, member, x_csrf_token)
            try:
                result = await service_for(member).unpublish(
                    session, actor_id=member.account_id, expected_version=payload.version
                )
            except (
                ProfileForbiddenError,
                ProfileConflictError,
                ProfileValidationError,
                ProfileInfrastructureError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise map_profile_error(error) from error
        response.headers["Cache-Control"] = "no-store"
        return _response(result)

    @routes.post("/me/profile/photo-uploads", response_model=PhotoUploadResponse, status_code=201)
    async def create_photo_upload(
        payload: PhotoUploadRequest,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> PhotoUploadResponse:
        check_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            check_csrf(request, member, x_csrf_token)
            upload_id = uuid7()
            try:
                upload = await storage.create_staging_upload(
                    account_id=member.account_id,
                    upload_id=upload_id,
                    content_type=payload.content_type,
                    size=payload.size,
                )
                await service_for(member).repository.create_photo_upload(
                    session,
                    account_id=member.account_id,
                    upload_id=upload_id,
                    staging_key=upload.object_key,
                    expires_in=upload.expires_in,
                )
            except (
                ObjectValidationError,
                ObjectNotFound,
                ObjectOperationError,
                ProfileConflictError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise _map_storage_error(error) from error
        return PhotoUploadResponse(
            upload_id=upload_id,
            upload_url=upload.upload_url,
            fields=upload.fields,
            expires_in=upload.expires_in,
        )

    @routes.post(
        "/me/profile/photo-uploads/{upload_id}/complete",
        response_model=PhotoCompleteResponse,
    )
    async def complete_photo_upload(
        upload_id: UUID,
        request: Request,
        session: DbSession,
        x_csrf_token: str | None = Header(default=None),
    ) -> PhotoCompleteResponse:
        check_origin(request)
        async with session.begin():
            member = await current_member(request, session)
            check_csrf(request, member, x_csrf_token)
            try:
                completed = await service_for(member).repository.get_completed_photo(
                    session, account_id=member.account_id, upload_id=upload_id
                )
                if completed is not None:
                    _, media_type, byte_count = completed
                    return PhotoCompleteResponse(
                        upload_id=upload_id, media_type=media_type, byte_count=byte_count
                    )
                photo: CleanPhoto = await storage.finalize_staging(
                    account_id=member.account_id, upload_id=upload_id
                )
                completed = await service_for(member).repository.complete_photo_upload(
                    session,
                    account_id=member.account_id,
                    upload_id=upload_id,
                    clean_key=photo.object_key,
                    media_type=photo.media_type,
                    byte_count=photo.byte_count,
                )
                if not completed:
                    raise ProfileConflictError("photo upload is no longer pending")
            except (
                ObjectValidationError,
                ObjectNotFound,
                ObjectOperationError,
                ProfileConflictError,
                SQLAlchemyError,
                RedisError,
            ) as error:
                raise _map_storage_error(error) from error
        return PhotoCompleteResponse(
            upload_id=upload_id, media_type=photo.media_type, byte_count=photo.byte_count
        )

    @routes.get("/profiles/{account_id}/photo")
    async def profile_photo(
        account_id: UUID, request: Request, response: Response, session: DbSession
    ) -> StreamingResponse:
        member: MemberContext | None = None
        secret = request.cookies.get(settings.session_cookie_name)
        if secret:
            try:
                member = await session_service.resolve(session, session_secret=secret)
            except UnauthenticatedError:
                member = None
        service = service_for(member)
        try:
            result = await service.get_public(session, account_id=account_id)
            if result is None and member is not None and member.account_id == account_id:
                result = await service.get_owner(
                    session, actor_id=member.account_id, account_id=account_id
                )
            if result is None or result.profile.photo_key is None:
                raise ObjectNotFound("photo unavailable")
            body, media_type = await storage.get_private(object_key=result.profile.photo_key)
        except ObjectNotFound as error:
            raise HTTPException(status_code=404, detail="photo unavailable") from error
        except (ObjectOperationError, SQLAlchemyError) as error:
            raise HTTPException(status_code=503, detail="service unavailable") from error
        image = StreamingResponse(
            iter((body,)), media_type=media_type or "application/octet-stream"
        )
        image.headers["Cache-Control"] = "no-store"
        image.headers["X-Content-Type-Options"] = "nosniff"
        return image

    async def graphql_context(request: Request) -> dict[str, object]:
        if request.method != "POST":
            raise HTTPException(status_code=405, detail="POST required")
        body = await request.body()
        try:
            payload = json.loads(body)
            query = payload.get("query") if isinstance(payload, dict) else None
            if not isinstance(query, str):
                raise ValueError("query is required")
            validate_read_query(query)
        except (GraphQLError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=400, detail="query is not allowed") from error
        async with session_factory() as session:
            member: MemberContext | None = None
            secret = request.cookies.get(settings.session_cookie_name)
            if secret:
                try:
                    member = await session_service.resolve(session, session_secret=secret)
                except UnauthenticatedError:
                    member = None
        return {
            "member": member,
            "session_factory": session_factory,
            "service_factory": service_for,
        }

    graphql_routes = build_router(graphql_context)
    return routes, graphql_routes


def _response(result: ProfileResult, *, became_private: bool = False) -> ProfileResponse:
    return ProfileResponse(
        account_id=result.profile.account_id,
        display_name=result.profile.display_name,
        bio=result.profile.bio,
        photo_url=(
            f"/api/v1/profiles/{result.profile.account_id}/photo"
            if result.profile.photo_key
            else None
        ),
        links=result.links,
        visibility=result.profile.visibility,
        published_at=result.profile.published_at,
        version=result.profile.version,
        became_private=became_private,
    )


def _map_storage_error(error: Exception) -> HTTPException:
    if isinstance(error, ObjectValidationError):
        return HTTPException(status_code=422, detail="invalid photo upload")
    if isinstance(error, ObjectNotFound):
        return HTTPException(status_code=404, detail="photo upload unavailable")
    if isinstance(error, ProfileConflictError):
        return HTTPException(status_code=409, detail="photo upload is no longer pending")
    if isinstance(error, (ObjectOperationError, SQLAlchemyError, RedisError)):
        return HTTPException(status_code=503, detail="service unavailable")
    return HTTPException(status_code=400, detail="photo upload could not be completed")
