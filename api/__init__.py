# api/__init__.py — router package (D-010; INTERFACE_CONTRACTS §2.1).
# app.py is the composition root and includes each router with prefix="/api".
from .settings import router as settings_router
from .intake import router as intake_router
from .jobs import router as jobs_router
from .system import router as system_router
from .staged import router as staged_router
from .contacts import router as contacts_router
from .emails import router as emails_router
from .quality import router as quality_router
from .history import router as history_router

__all__ = [
    "settings_router",
    "intake_router",
    "jobs_router",
    "system_router",
    "staged_router",
    "contacts_router",
    "emails_router",
    "quality_router",
    "history_router",
]