import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.env import VAPID_PUBLIC_KEY
from open_webui.models.push_subscriptions import PushSubscriptions
from open_webui.utils.auth import get_verified_user
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


############################
# GetVapidPublicKey
############################


@router.get('/vapid-public-key')
async def get_vapid_public_key():
    return {'vapid_public_key': VAPID_PUBLIC_KEY}


############################
# Subscribe
############################


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeForm(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


@router.post('/subscribe')
async def subscribe(request: Request, form_data: SubscribeForm, user=Depends(get_verified_user)):
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Push notifications are not configured on this server.',
        )

    subscription = await PushSubscriptions.upsert_by_endpoint(
        user_id=user.id,
        endpoint=form_data.endpoint,
        p256dh=form_data.keys.p256dh,
        auth=form_data.keys.auth,
        user_agent=request.headers.get('user-agent'),
    )
    return subscription


############################
# Unsubscribe
############################


class UnsubscribeForm(BaseModel):
    endpoint: str


@router.post('/unsubscribe')
async def unsubscribe(form_data: UnsubscribeForm, user=Depends(get_verified_user)):
    await PushSubscriptions.delete_by_endpoint(form_data.endpoint)
    return True
