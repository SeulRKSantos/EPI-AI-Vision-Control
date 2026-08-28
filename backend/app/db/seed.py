"""Development seed data.

Populates PPE types, roles, their requirement matrix, a gate and a few
employees, so the decision logic can be exercised end to end without a
manual setup. Idempotent: running it twice leaves the same state.

Usage:  python -m app.db.seed
"""

import asyncio
import logging

from sqlalchemy import select

from app.core.logging import configure_logging
from app.db.models import Employee, Gate, PPEType, Role
from app.db.session import SessionFactory, dispose_engine

logger = logging.getLogger(__name__)

# `code` must match the class names the vision model outputs.
PPE_TYPES = [
    ("helmet", "Capacete", "Capacete de segurança"),
    ("goggles", "Óculos", "Óculos de proteção"),
    ("mask", "Máscara", "Máscara ou respirador"),
    ("gloves", "Luvas", "Luvas de proteção"),
    ("vest", "Colete", "Colete refletivo"),
    ("ear_protection", "Protetor auricular", "Protetor auditivo"),
    ("boots", "Botas", "Calçado de segurança"),
]

# role code -> (name, description, required PPE codes)
ROLES = {
    "operator": (
        "Operador",
        "Operador de máquinas na área produtiva",
        ["helmet", "goggles", "gloves", "boots"],
    ),
    "electrician": (
        "Eletricista",
        "Manutenção elétrica industrial",
        ["helmet", "goggles", "gloves", "boots"],
    ),
    "technician": (
        "Técnico",
        "Técnico de manutenção mecânica",
        ["helmet", "goggles", "boots"],
    ),
    "visitor": (
        "Visitante",
        "Acompanhante autorizado em visita à planta",
        ["helmet", "vest"],
    ),
}

GATES = [
    ("gate-01", "Portão da produção", "Entrada principal da área produtiva"),
]

# badge_id, name, registration, role code
EMPLOYEES = [
    ("BADGE001", "Funcionário Operação", "1001", "operator"),
    ("BADGE002", "Funcionário Elétrica", "1002", "electrician"),
    ("BADGE003", "Funcionário Manutenção", "1003", "technician"),
    ("BADGE004", "Visitante Autorizado", "1004", "visitor"),
]


async def seed() -> None:
    async with SessionFactory() as session:
        # --- PPE types ---
        existing_ppe = {
            code for (code,) in (await session.execute(select(PPEType.code))).all()
        }
        ppe_by_code: dict[str, PPEType] = {}
        for code, label, description in PPE_TYPES:
            if code in existing_ppe:
                ppe_by_code[code] = (
                    await session.execute(select(PPEType).where(PPEType.code == code))
                ).scalar_one()
                continue
            ppe = PPEType(code=code, label=label, description=description)
            session.add(ppe)
            ppe_by_code[code] = ppe
        await session.flush()

        # --- Roles and their requirement matrix ---
        for code, (name, description, required_codes) in ROLES.items():
            role = (
                await session.execute(select(Role).where(Role.code == code))
            ).scalar_one_or_none()
            if role is None:
                role = Role(code=code, name=name, description=description)
                session.add(role)
            role.required_ppe = [ppe_by_code[c] for c in required_codes]
        await session.flush()

        # --- Gates ---
        for code, name, location in GATES:
            gate = (
                await session.execute(select(Gate).where(Gate.code == code))
            ).scalar_one_or_none()
            if gate is None:
                session.add(Gate(code=code, name=name, location=location))
        await session.flush()

        # --- Employees ---
        for badge_id, name, registration, role_code in EMPLOYEES:
            employee = (
                await session.execute(
                    select(Employee).where(Employee.badge_id == badge_id)
                )
            ).scalar_one_or_none()
            role = (
                await session.execute(select(Role).where(Role.code == role_code))
            ).scalar_one()
            if employee is None:
                session.add(
                    Employee(
                        badge_id=badge_id,
                        name=name,
                        registration=registration,
                        role_id=role.id,
                    )
                )
            else:
                employee.role_id = role.id

        await session.commit()

    logger.info(
        "Seed completed",
        extra={
            "ppe_types": len(PPE_TYPES),
            "roles": len(ROLES),
            "gates": len(GATES),
            "employees": len(EMPLOYEES),
        },
    )


async def main() -> None:
    configure_logging()
    try:
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
