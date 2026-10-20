"""Per-user preferences (Feature 006).

- GET /api/preferences/appearance  -> {"appearance": ..., "chosen": bool}
- PUT /api/preferences/appearance  {"appearance": "light" | "dark" | "system"}

A user who has never chosen gets "system" with ``chosen: false``, so the
default is never mistaken for a stored choice. A database that is not
available is a 503, never a silent default.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.gateway.deps import get_user_preference_repo

router = APIRouter(prefix="/api/preferences", tags=["preferences"])

Appearance = Literal["system", "light", "dark"]


class AppearanceResponse(BaseModel):
    appearance: Appearance
    chosen: bool


class AppearanceUpdate(BaseModel):
    appearance: Appearance


def _user(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if auth and auth.user:
        return str(auth.user.id)
    raise HTTPException(status_code=401, detail="Authentication required")


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
