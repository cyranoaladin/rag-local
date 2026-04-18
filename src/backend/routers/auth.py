"""Authentication endpoints."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import deps
from ..core.config import get_settings
from ..core.security import create_access_token, hash_password, verify_password
from ..models.user import User
from ..schemas.user import Token, UserCreate, UserRead

router = APIRouter()


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(deps.get_db)) -> User:  # noqa: B008
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Utilisateur déjà enregistré")
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(deps.get_db)) -> Token:  # noqa: B008
    user = db.query(User).filter(User.email == form_data.username.lower()).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
    settings = get_settings()
    expires = timedelta(minutes=settings.access_token_expire_minutes)
    token = create_access_token(subject=user.email, expires_delta=expires)
    return Token(access_token=token)
