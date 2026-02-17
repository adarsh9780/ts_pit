from .agent import router as agent_router
from .alerts import router as alerts_router
from .market import router as market_router
from .reports import router as reports_router
from .settings import router as settings_router

__all__ = [
    "agent_router",
    "alerts_router",
    "market_router",
    "reports_router",
    "settings_router",
]

