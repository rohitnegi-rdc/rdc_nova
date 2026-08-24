import { describe, expect, it } from 'vitest';

import { canSelectMultipleModels, normalizeSelectedModelsForRole } from './model-selection';

describe('model selection permissions', () => {
	it('allows only admins to compare multiple models', () => {
		expect(canSelectMultipleModels('admin')).toBe(true);
		expect(canSelectMultipleModels('user')).toBe(false);
		expect(canSelectMultipleModels(undefined)).toBe(false);
	});

	it('preserves multiple selections for admins', () => {
		expect(normalizeSelectedModelsForRole(['nova-v2', 'nova'], 'admin')).toEqual([
			'nova-v2',
			'nova'
		]);
	});

	it('keeps only one model for non-admin users', () => {
		expect(normalizeSelectedModelsForRole(['nova-v2', 'nova'], 'user')).toEqual(['nova-v2']);
		expect(normalizeSelectedModelsForRole(['', 'nova'], 'user')).toEqual(['nova']);
	});

	it('always leaves a usable selector row', () => {
		expect(normalizeSelectedModelsForRole([], 'user')).toEqual(['']);
		expect(normalizeSelectedModelsForRole(undefined, 'admin')).toEqual(['']);
	});
});
