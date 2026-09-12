"""Transaction-scoped audit events with server-selected metadata only."""

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.observability import request_id_context


def record_event(
    session: Session,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            safe_metadata=metadata,
            request_id=request_id_context.get(),
        )
    )
