"""Aggregates the v1 routers."""

from fastapi import APIRouter

from app.api.v1 import access_logs, employees, gates, health, ppe_types, roles

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(ppe_types.router)
api_router.include_router(roles.router)
api_router.include_router(employees.router)
api_router.include_router(access_logs.router)
api_router.include_router(gates.router)
