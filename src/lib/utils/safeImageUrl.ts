import { WEBUI_BASE_URL } from '$lib/constants';

const PLACEHOLDER_IMAGE = '/static/favicon.png';

export function resolveSafeImageUrl(url: string, baseUrl: string): string {
	const placeholder = `${baseUrl}${PLACEHOLDER_IMAGE}`;

	if (!url) {
		return placeholder;
	}

	if (
		(baseUrl && (url === baseUrl || url.startsWith(`${baseUrl}/`))) ||
		url.startsWith('https://www.gravatar.com/avatar/') ||
		url.startsWith('data:image')
	) {
		return url;
	}

	if (url.startsWith('/')) {
		return `${baseUrl}${url}`;
	}

	return placeholder;
}

/**
 * Validates an image URL against an allowlist of safe patterns and returns
 * the URL if trusted, or a placeholder otherwise.
 *
 * Allowed patterns:
 *   - Relative paths (starting with '/')
 *   - data:image/* URIs
 *   - Same-origin URLs (starting with WEBUI_BASE_URL)
 *   - Gravatar URLs (https://www.gravatar.com/avatar/)
 *
 * All other URLs (including arbitrary http(s):// origins) are rejected to
 * prevent client-side IP/UA/Referer leaks to attacker-controlled servers.
 */
export function safeImageUrl(url: string): string {
	return resolveSafeImageUrl(url, WEBUI_BASE_URL);
}
