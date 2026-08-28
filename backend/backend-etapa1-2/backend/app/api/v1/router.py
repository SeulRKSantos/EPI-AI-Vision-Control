"""Aggregates the v1 routers.

Administration routers (employees, roles, PPE types, access logs) are added
in stage 3.
"""

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
