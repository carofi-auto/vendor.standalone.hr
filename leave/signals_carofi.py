"""
Carofi-specific outbound webhook for LeaveRequest status changes.

When a LeaveRequest is created or its status transitions, this module posts an
HMAC-signed JSON payload to the carofi BFF (server.connect.admin), which in
turn fans the event out to the carofi notification service so the requesting
employee receives a browser push + in-app notification inside client.web.admin.

Failures are swallowed and logged so this never blocks horilla's request thread
or rolls back a leave-status update.
"""

import hashlib
import hmac
import json
import logging
import threading

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

import requests

from .models import LeaveRequest

logger = logging.getLogger(__name__)


def _payload_for(instance: LeaveRequest, prev_status):
    employee = instance.employee_id
    leave_type = instance.leave_type_id
    return {
        "request_id": instance.id,
        "employee_id": getattr(employee, "id", None),
        "employee_email": (getattr(employee, "email", "") or "").strip().lower(),
        "status": instance.status,
        "prev_status": prev_status,
        "leave_type": getattr(leave_type, "name", None),
        "leave_type_id": getattr(leave_type, "id", None),
        "start_date": instance.start_date.isoformat() if instance.start_date else None,
        "end_date": instance.end_date.isoformat() if instance.end_date else None,
        "requested_days": instance.requested_days,
        "updated_at": timezone.localtime(timezone.now()).isoformat(),
    }


def _post_webhook(payload: dict) -> None:
    url = getattr(settings, "CAROFI_LEAVE_WEBHOOK_URL", "") or ""
    secret = getattr(settings, "CAROFI_LEAVE_WEBHOOK_SECRET", "") or ""
    if not url or not secret:
        return

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    try:
        requests.post(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Carofi-Signature": f"sha256={signature}",
            },
            timeout=5,
        )
    except Exception:  # noqa: BLE001 — webhook must never break leave save
        logger.exception(
            "carofi leave webhook delivery failed for request_id=%s",
            payload.get("request_id"),
        )


@receiver(pre_save, sender=LeaveRequest)
def _capture_previous_status(sender, instance: LeaveRequest, **kwargs):
    """Stash the previous status so post_save can detect transitions."""
    if instance.pk:
        try:
            instance._prev_status = (
                LeaveRequest.objects.only("status").get(pk=instance.pk).status
            )
        except LeaveRequest.DoesNotExist:
            instance._prev_status = None
    else:
        instance._prev_status = None


@receiver(post_save, sender=LeaveRequest)
def _notify_carofi_on_status_change(
    sender, instance: LeaveRequest, created, **kwargs
):
    prev_status = getattr(instance, "_prev_status", None)
    if not created and instance.status == prev_status:
        return

    payload = _payload_for(instance, prev_status)

    def _dispatch():
        threading.Thread(
            target=_post_webhook,
            args=(payload,),
            daemon=True,
        ).start()

    transaction.on_commit(_dispatch)
