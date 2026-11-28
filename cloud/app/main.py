from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import User
from .routes import router
from .security import hash_password

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
        with SessionLocal() as db:
            email = settings.bootstrap_admin_email.strip().lower()
            existing = db.scalar(select(User).where(User.email == email))
            if not existing:
                db.add(
                    User(
                        email=email,
                        password_hash=hash_password(settings.bootstrap_admin_password),
                        role="admin",
                        is_active=True,
                    )
                )
                db.commit()
    yield


app = FastAPI(
    title="ZeroCode Cloud API",
    description="Central AI gateway, user sessions and remote control plane for ZeroCode clients.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "ZeroCode Cloud", "status": "running", "api": settings.api_prefix}
