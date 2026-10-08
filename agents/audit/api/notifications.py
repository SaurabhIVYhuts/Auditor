"""Notification API: the signed-in user's in-app notifications (own + role-wide)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.audit.schemas.notification import NotificationOut
from shared.auth import CurrentUser, get_current_user
from shared.db import get_db
from shared.notifications import Notification, list_for_user, mark_read

router = APIRouter(tags=["notifications"])


def _out(notification: Notification) -> NotificationOut:
    return NotificationOut.model_validate(notification).model_copy(
        update={"for_role": notification.recipient_role})


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(unread_only: bool = False, user: CurrentUser = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    return [_out(n) for n in list_for_user(db, user.tenant_id, user.user_id, user.roles, unread_only)]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read(notification_id: uuid.UUID, user: CurrentUser = Depends(get_current_user),
         db: Session = Depends(get_db)):
    notification = mark_read(db, user.tenant_id, notification_id, user.user_id, user.roles)
    if notification is None:
        raise HTTPException(404, detail="Notification not found")
    db.commit()
    return _out(notification)
