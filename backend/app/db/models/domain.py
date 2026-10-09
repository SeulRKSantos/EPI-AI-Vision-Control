"""Domain entities: gates, roles, PPE types, requirements and employees."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# Many-to-many between a role and the PPE it requires.
# Declared as a Table (not a model) because it carries no attributes of its own.
role_ppe_requirements = Table(
    "role_ppe_requirements",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("ppe_type_id", ForeignKey("ppe_types.id", ondelete="CASCADE"), primary_key=True),
)


class Gate(Base, TimestampMixin):
    """A physical access point controlled by the system."""

    __tablename__ = "gates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Gate {self.code}>"


class PPEType(Base, TimestampMixin):
    """A recognized type of personal protective equipment.

    `code` is the coupling point with the vision model: it must match the
    class name the YOLO model was trained to output. The correspondence is
    validated at service startup.
    """

    __tablename__ = "ppe_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_ppe_requirements,
        back_populates="required_ppe",
    )

    def __repr__(self) -> str:
        return f"<PPEType {self.code}>"


class Role(Base, TimestampMixin):
    """A job role, which determines the PPE an employee must wear."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    required_ppe: Mapped[list[PPEType]] = relationship(
        secondary=role_ppe_requirements,
        back_populates="roles",
        lazy="selectin",  # loaded eagerly: always needed alongside the role
    )
    employees: Mapped[list["Employee"]] = relationship(back_populates="role")

    def __repr__(self) -> str:
        return f"<Role {self.code}>"


class Employee(Base, TimestampMixin):
    """An employee, identified at the gate by their badge."""

    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("badge_id", name="uq_employees_badge_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    badge_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    registration: Mapped[str | None] = mapped_column(String(50))
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role: Mapped[Role] = relationship(back_populates="employees", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Employee {self.badge_id}>"
