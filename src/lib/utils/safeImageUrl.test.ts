import { describe, expect, it } from 'vitest';

import { resolveSafeImageUrl } from './safeImageUrl';

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
});
