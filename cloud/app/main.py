from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path == "/admin" or request.url.path.startswith("/admin/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
    return response


app.include_router(router, prefix=settings.api_prefix)

ADMIN_WEB_DIR = Path(__file__).resolve().parent.parent / "admin"
app.mount(
    "/admin/assets",
    StaticFiles(directory=str(ADMIN_WEB_DIR), check_dir=True),
    name="admin-assets",
)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_dashboard():
    return FileResponse(
        ADMIN_WEB_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": "ZeroCode Cloud", "status": "running", "api": settings.api_prefix}
