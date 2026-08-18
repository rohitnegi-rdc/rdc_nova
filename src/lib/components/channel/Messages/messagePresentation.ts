type ChannelMessage = {
	content?: unknown;
	data?: unknown;
	meta?: unknown;
};

const loadedMessageData = (message: ChannelMessage | null | undefined): Record<string, unknown> =>
	typeof message?.data === 'object' && message.data !== null && !Array.isArray(message.data)
		? (message.data as Record<string, unknown>)
		: {};

export const channelStatusHistory = (message: ChannelMessage | null | undefined): unknown[] => {
	const statusHistory = loadedMessageData(message).statusHistory;
	return Array.isArray(statusHistory) ? statusHistory : [];
};

export const channelSources = (message: ChannelMessage | null | undefined): unknown[] => {
	const sources = loadedMessageData(message).sources;
	return Array.isArray(sources) ? sources : [];
};

export const shouldShowModelSkeleton = (message: ChannelMessage | null | undefined): boolean => {
	const meta =
		typeof message?.meta === 'object' && message.meta !== null
			? (message.meta as Record<string, unknown>)
			: {};
	const content = typeof message?.content === 'string' ? message.content : '';

	return (
		content.trim() === '' && Boolean(meta.model_id) && channelStatusHistory(message).length === 0
	);
};
