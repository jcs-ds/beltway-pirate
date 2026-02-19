"""API Router modules."""
from .entities import router as entities_router
from .stakeholders import router as stakeholders_router
from .programs import router as programs_router
from .platforms import router as platforms_router
from .units import router as units_router
from .competitors import router as competitors_router
from .political_affairs import router as political_affairs_router
from .technology import router as technology_router

__all__ = [
    'entities_router',
    'stakeholders_router',
    'programs_router',
    'platforms_router',
    'units_router',
    'competitors_router',
    'political_affairs_router',
    'technology_router',
]
