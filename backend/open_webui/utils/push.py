import json
import logging
from typing import Optional

from open_webui.env import VAPID_PRIVATE_KEY, VAPID_SUBJECT
from open_webui.models.push_subscriptions import PushSubscriptions
from pywebpush import WebPushException, webpush

log = logging.getLogger(__name__)


async def send_push_to_users(
    user_ids: list[str],
    title: str,
    body: str,
    url: str,
    tag: Optional[str] = None,
) -> None:
    """Send a Web Push notification to every subscribed device of the given users.

    Silently skips when VAPID keys are not configured (push disabled locally),
    and drops any subscription the push service reports as gone (404/410).
    """
    if not VAPID_PRIVATE_KEY:
        return

    payload = json.dumps({'title': title, 'body': body, 'url': url, 'tag': tag})

    for user_id in user_ids:
        subscriptions = await PushSubscriptions.get_by_user_id(user_id)
        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        'endpoint': subscription.endpoint,
                        'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                    },
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={'sub': VAPID_SUBJECT},
                )
            except WebPushException as e:
                status_code = getattr(e.response, 'status_code', None)
                if status_code in (404, 410):
                    await PushSubscriptions.delete_by_endpoint(subscription.endpoint)
                else:
                    log.warning(f'Push notification failed for user {user_id}: {e}')
            except Exception as e:
                log.warning(f'Push notification failed for user {user_id}: {e}')
