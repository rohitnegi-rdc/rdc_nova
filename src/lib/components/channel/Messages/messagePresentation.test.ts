import { describe, expect, it } from 'vitest';

import {
	channelSources,
	channelStatusHistory,
	shouldShowModelSkeleton
} from './messagePresentation';

describe('channel message presentation', () => {
	it('reads persisted status history and sources from channel message data', () => {
		const message = {
			content: 'Grounded answer [1]',
			meta: { model_id: 'nova_v2' },
			data: {
				statusHistory: [{ action: 'retrieve', description: 'Searching knowledge base' }],
				sources: [{ source: { id: 'kb-1', name: 'IDS guide' } }]
			}
		};

		expect(channelStatusHistory(message)).toEqual(message.data.statusHistory);
		expect(channelSources(message)).toEqual(message.data.sources);
	});

	it('does not show the bouncing skeleton once progress is available', () => {
		const generating = { content: '', meta: { model_id: 'nova_v2' }, data: {} };
		const progressing = {
			...generating,
			data: { statusHistory: [{ action: 'retrieve', description: 'Searching knowledge base' }] }
		};

		expect(shouldShowModelSkeleton(generating)).toBe(true);
		expect(shouldShowModelSkeleton(progressing)).toBe(false);
		expect(shouldShowModelSkeleton({ ...progressing, content: 'Answer' })).toBe(false);
	});

	it('handles slim channel messages whose data has not loaded yet', () => {
		const message = { content: '', meta: { model_id: 'nova_v2' }, data: true };

		expect(channelStatusHistory(message)).toEqual([]);
		expect(channelSources(message)).toEqual([]);
		expect(shouldShowModelSkeleton(message)).toBe(true);
	});
});
