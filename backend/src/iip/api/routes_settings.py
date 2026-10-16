"""Settings API for notifications and wording (PLAN.md wave 2, C04 over B04; U-09, U-11).

* ``GET /api/settings/vocabulary`` → ``{mode}``: ``neutral`` (default) or ``badges`` — the same wire values as
  :class:`iip.supervisor.compliance.Vocabulary` and ``VocabularyMode`` in ``frontend/src/lib/types-settings.ts``.
* ``PUT /api/settings/vocabulary`` ``{mode, acknowledge_private_only}``: ``badges`` needs the acknowledgement.
* ``GET /api/settings/notifications`` → the channel that can actually deliver (``off`` in v1), the channels
  available, what ``IIP_NOTIFY`` asks for and the exact ping text.
* ``PUT /api/settings/notifications`` ``{channel, acknowledge_third_party_storage}``: validated against what the
  server can deliver; the channel itself is set by ``IIP_NOTIFY`` (nothing is stored), so switching a channel on
  without a transport is refused with ``CHANNEL_UNAVAILABLE``.

State-changing routes go through the same session and CSRF middleware as every other route.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from iip.services import settings_prefs as prefs
from iip.supervisor.compliance import Vocabulary

_STATUS = {"ACK_REQUIRED": 422, "CHANNEL_UNAVAILABLE": 409, "CHANNEL_SET_BY_ENVIRONMENT": 409}


class VocabularyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Vocabulary
    acknowledge_private_only: bool = False


class NotificationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["off", "webpush", "telegram"]
    acknowledge_third_party_storage: bool = False


def _reject(exc: prefs.PreferenceRejected) -> HTTPException:
    return HTTPException(_STATUS.get(exc.code, 422), {"code": exc.code, "message": str(exc)})


def router() -> APIRouter:
    r = APIRouter(prefix="/api/settings", tags=["settings"])

    @r.get("/vocabulary")
    def get_vocabulary(request: Request) -> dict[str, Any]:
        return {"mode": prefs.read_vocabulary(request.app.state.iip.conn).value}

    @r.put("/vocabulary")
    def put_vocabulary(body: VocabularyIn, request: Request) -> dict[str, Any]:
        try:
            mode = prefs.write_vocabulary(
                request.app.state.iip.conn, body.mode, acknowledge_private_only=body.acknowledge_private_only
            )
        except prefs.PreferenceRejected as exc:
            raise _reject(exc) from exc
        return {"mode": mode.value}

    @r.get("/notifications")
    def get_notifications() -> dict[str, Any]:
        return prefs.notification_view(os.environ).as_json()

    @r.put("/notifications")
    def put_notifications(body: NotificationsIn) -> dict[str, Any]:
        try:
            view = prefs.check_notification_change(
                os.environ, body.channel, acknowledge_third_party_storage=body.acknowledge_third_party_storage
            )
        except prefs.PreferenceRejected as exc:
            raise _reject(exc) from exc
        return view.as_json()

    return r
