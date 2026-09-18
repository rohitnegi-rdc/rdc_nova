import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getVapidPublicKey = async () => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/push/vapid-public-key`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json'
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res?.vapid_public_key ?? null;
};

export const subscribeToPush = async (token: string, subscription: PushSubscriptionJSON) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/push/subscribe`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(subscription)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const unsubscribeFromPush = async (token: string, endpoint: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/push/unsubscribe`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ endpoint })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
