import { base } from '$app/paths';

export const prefixAppPath = (path: string, basePath: string): string => {
	if (!basePath || !path.startsWith('/') || path.startsWith('//')) {
		return path;
	}

	if (
		path === basePath ||
		path.startsWith(`${basePath}/`) ||
		path.startsWith(`${basePath}?`) ||
		path.startsWith(`${basePath}#`)
	) {
		return path;
	}

	return `${basePath}${path}`;
};

export const appPath = (path: string): string => prefixAppPath(path, base);
