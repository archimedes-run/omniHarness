"""Per-user preferences (Feature 006).

- GET /api/preferences -> everything below, in one read
- GET /api/preferences/appearance -> {"appearance": ..., "chosen": bool}
- PUT /api/preferences/appearance  {"appearance": "light" | "dark" | "system"}
- PUT /api/preferences/display-name {"display_name": str | null}

A user who has never chosen an appearance gets "system" with
``chosen: false``, so the default is never mistaken for a stored choice. The
display name is optional; ``display_name_effective`` applies the one fallback
rule (the email before "@") so every UI shows the same name. A database that
is not available is a 503, never a silent default.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.deps import get_user_preference_repo
from omniharness.persistence.user_preferences import DISPLAY_NAME_MAX, effective_display_name

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

Appearance = Literal["system", "light", "dark"]


class AppearanceResponse(BaseModel):
    appearance: Appearance
    chosen: bool


class AppearanceUpdate(BaseModel):
    appearance: Appearance


class DisplayNameUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX)


class PreferencesResponse(BaseModel):
    appearance: Appearance
    appearance_chosen: bool
    #: What the user set, or null when unset.
    display_name: str | None
    #: The name to show: display_name, else the email before "@".
    display_name_effective: str


def _auth_user(request: Request):
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return auth.user
    raise HTTPException(status_code=401, detail="Authentication required")


def _user(request: Request) -> str:
    return str(_auth_user(request).id)


async def _all(request: Request) -> PreferencesResponse:
    user = _auth_user(request)
    repo = get_user_preference_repo(request)
    appearance = await repo.get_appearance(user_id=str(user.id))
    name = await repo.get_display_name(user_id=str(user.id))
    return PreferencesResponse(
        appearance=appearance or "system",  # type: ignore[arg-type]
        appearance_chosen=appearance is not None,
        display_name=name,
        display_name_effective=effective_display_name(name, str(user.email)),
    )


@router.get("", response_model=PreferencesResponse)
async def get_preferences(request: Request) -> PreferencesResponse:
    return await _all(request)


@router.put("/display-name", response_model=PreferencesResponse)
async def put_display_name(body: DisplayNameUpdate, request: Request) -> PreferencesResponse:
    await get_user_preference_repo(request).set_display_name(user_id=_user(request), display_name=body.display_name)
    return await _all(request)


@router.get("/appearance", response_model=AppearanceResponse)
async def get_appearance(request: Request) -> AppearanceResponse:
    user_id = _user(request)
    stored = await get_user_preference_repo(request).get_appearance(user_id=user_id)
    if stored is None:
        return AppearanceResponse(appearance="system", chosen=False)
    return AppearanceResponse(appearance=stored, chosen=True)  # type: ignore[arg-type]


@router.put("/appearance", response_model=AppearanceResponse)
async def put_appearance(body: AppearanceUpdate, request: Request) -> AppearanceResponse:
    user_id = _user(request)
    saved = await get_user_preference_repo(request).set_appearance(user_id=user_id, appearance=body.appearance)
    return AppearanceResponse(appearance=saved, chosen=True)  # type: ignore[arg-type]
