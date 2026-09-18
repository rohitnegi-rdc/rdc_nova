self.addEventListener('install', () => {
	self.skipWaiting();
});

self.addEventListener('activate', (event) => {
	event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
	if (!event.data) {
		return;
	}

	let payload;
	try {
		payload = event.data.json();
	} catch {
		payload = { title: 'Open WebUI', body: event.data.text() };
	}

	const { title, body, url, tag } = payload;

	event.waitUntil(
		self.registration.showNotification(title || 'Open WebUI', {
			body: body || '',
			icon: '/logos/apple-touch-icon.png',
			badge: '/logos/favicon-32x32.png',
			tag: tag || undefined,
			requireInteraction: true,
			data: { url: url || '/' }
		})
	);
});

self.addEventListener('notificationclick', (event) => {
	event.notification.close();

	const targetUrl = event.notification.data?.url || '/';

	event.waitUntil(
		(async () => {
			const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });

			for (const client of clientsList) {
				if ('focus' in client) {
					await client.focus();
					client.postMessage({ type: 'push-notification-click', url: targetUrl });
					return;
				}
			}

			await self.clients.openWindow(targetUrl);
		})()
	);
});
