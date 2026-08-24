import { goto as kitGoto } from '$app/navigation';
import { appPath } from '$lib/utils/app-path';

export * from '$app/navigation';

export const goto = (
	url: Parameters<typeof kitGoto>[0],
	options?: Parameters<typeof kitGoto>[1]
): ReturnType<typeof kitGoto> => kitGoto(typeof url === 'string' ? appPath(url) : url, options);
