import { base } from '$app/paths';
import { getVapidPublicKey, subscribeToPush, unsubscribeFromPush } from '$lib/apis/push';

const urlBase64ToUint8Array = (base64String: string): Uint8Array => {
	const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
	const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');

	const rawData = window.atob(base64);
	const outputArray = new Uint8Array(rawData.length);

	for (let i = 0; i < rawData.length; ++i) {
		outputArray[i] = rawData.charCodeAt(i);
	}

	return outputArray;
};

export const isPushSupported = () =>
	typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window;

export const registerServiceWorker = async (): Promise<ServiceWorkerRegistration | null> => {
	if (!isPushSupported()) {
		return null;
	}

	try {
		return await navigator.serviceWorker.register(`${base}/sw.js`, {
			scope: `${base}/`
		});
	} catch (error) {
		console.error('Service worker registration failed', error);
		return null;
	}
};

export const enablePushNotifications = async (token: string): Promise<boolean> => {
	if (!isPushSupported()) {
		return false;
	}

	try {
		const registration = await registerServiceWorker();
		if (!registration) {
			return false;
		}

		const vapidPublicKey = await getVapidPublicKey().catch(() => null);
		if (!vapidPublicKey) {
			// Push is not configured on this server yet (no VAPID keys) — nothing to do.
			return false;
		}

		let subscription = await registration.pushManager.getSubscription();
		if (!subscription) {
			subscription = await registration.pushManager.subscribe({
				userVisibleOnly: true,
				applicationServerKey: urlBase64ToUint8Array(vapidPublicKey) as BufferSource
			});
		}

		await subscribeToPush(token, subscription.toJSON() as PushSubscriptionJSON);
		return true;
	} catch (error) {
		console.error('Failed to enable push notifications', error);
		return false;
	}
};

export const disablePushNotifications = async (token: string): Promise<void> => {
	if (!isPushSupported()) {
		return;
	}

	try {
		const registration = await navigator.serviceWorker.getRegistration(`${base}/`);
		const subscription = await registration?.pushManager.getSubscription();

		if (subscription) {
			await unsubscribeFromPush(token, subscription.endpoint).catch(() => {});
			await subscription.unsubscribe();
		}
	} catch (error) {
		console.error('Failed to disable push notifications', error);
	}
};
