import { afterEach, describe, expect, it, vi } from 'vitest';

import { applyImageFallback, resolveSafeImageUrl } from './safeImageUrl';

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('resolveSafeImageUrl', () => {
	it('prefixes root-relative images for a subpath deployment', () => {
		expect(resolveSafeImageUrl('/static/favicon.png', '/opsmitra')).toBe(
			'/opsmitra/static/favicon.png'
		);
	});

	it('does not duplicate an existing application prefix', () => {
		expect(resolveSafeImageUrl('/opsmitra/api/v1/users/1/profile/image', '/opsmitra')).toBe(
			'/opsmitra/api/v1/users/1/profile/image'
		);
	});

	it('uses the application-scoped placeholder for unsafe images', () => {
		expect(resolveSafeImageUrl('https://untrusted.example/avatar.png', '/opsmitra')).toBe(
			'/opsmitra/static/favicon.png'
		);
	});

	it('preserves approved image data and root deployments', () => {
		expect(resolveSafeImageUrl('data:image/png;base64,AA==', '/opsmitra')).toBe(
			'data:image/png;base64,AA=='
		);
		expect(resolveSafeImageUrl('/static/favicon.png', '')).toBe('/static/favicon.png');
	});

	it('applies the scoped fallback once without restarting an error loop', () => {
		vi.stubGlobal('window', { location: { origin: 'https://suraksha.rdcc.ai' } });
		const image = { src: 'https://suraksha.rdcc.ai/opsmitra/api/v1/models/missing' };
		const event = { currentTarget: image } as unknown as Event;

		applyImageFallback(event, '/opsmitra');
		expect(image.src).toBe('/opsmitra/static/favicon.png');

		image.src = 'https://suraksha.rdcc.ai/opsmitra/static/favicon.png';
		applyImageFallback(event, '/opsmitra');
		expect(image.src).toBe('https://suraksha.rdcc.ai/opsmitra/static/favicon.png');
	});
});
