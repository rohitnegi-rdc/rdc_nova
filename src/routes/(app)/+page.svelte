<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Chat from '$lib/components/chat/Chat.svelte';
	import { page } from '$app/stores';
	import { goto } from '$lib/navigation';
	import { channels, config } from '$lib/stores';

	let unsubscribeChannels: (() => void) | undefined;

	$: directChatEnabled = $config?.features?.enable_direct_chat ?? true;

	onMount(() => {
		if ($page.url.searchParams.get('error')) {
			toast.error($page.url.searchParams.get('error') || 'An unknown error occurred.');
		}

		unsubscribeChannels = channels.subscribe((value) => {
			if (($config?.features?.enable_direct_chat ?? true) === false && value?.[0]?.id) {
				goto(`/channels/${value[0].id}`);
			}
		});
	});

	onDestroy(() => {
		unsubscribeChannels?.();
	});
</script>

{#if directChatEnabled}
	<Chat />
{/if}
