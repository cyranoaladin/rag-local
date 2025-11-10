"""User-facing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import deps
from ..models.user import User
from ..schemas.user import UserRead

router = APIRouter()


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(deps.get_current_user)) -> User:  # noqa: B008
    return current_user
