import { describe, expect, it } from 'vitest';

import { prefixAppPath } from './app-path';

describe('prefixAppPath', () => {
	it('prefixes root-relative application paths', () => {
		expect(prefixAppPath('/auth?redirect=%2F', '/opsmitra')).toBe(
			'/opsmitra/auth?redirect=%2F'
		);
	});

	it('does not prefix an application path twice', () => {
		expect(prefixAppPath('/opsmitra/channels/123', '/opsmitra')).toBe(
			'/opsmitra/channels/123'
		);
	});

	it('leaves external and non-root-relative targets unchanged', () => {
		expect(prefixAppPath('https://example.com/auth', '/opsmitra')).toBe(
			'https://example.com/auth'
		);
		expect(prefixAppPath('//cdn.example.com/app.js', '/opsmitra')).toBe(
			'//cdn.example.com/app.js'
		);
		expect(prefixAppPath('?model=nova', '/opsmitra')).toBe('?model=nova');
	});

	it('preserves root deployment behavior when no base path is configured', () => {
		expect(prefixAppPath('/auth', '')).toBe('/auth');
	});
});
