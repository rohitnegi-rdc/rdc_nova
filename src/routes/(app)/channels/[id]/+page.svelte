<script lang="ts">
	import { page } from '$app/stores';

	import Channel from '$lib/components/channel/Channel.svelte';
</script>

<Channel
	id={$page.params.id}
	deepLinkThreadId={$page.url.searchParams.get('thread')}
	deepLinkMessageId={$page.url.searchParams.get('message')}
/>
