from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, q: Select, page: int, page_size: int) -> tuple[list[Any], int]:
    total = db.execute(select(func.count()).select_from(q.order_by(None).subquery())).scalar_one()
    rows = db.execute(q.limit(page_size).offset((page - 1) * page_size)).scalars().all()
    return list(rows), int(total)
