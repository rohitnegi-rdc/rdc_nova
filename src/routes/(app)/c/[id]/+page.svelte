<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/stores';

	import Chat from '$lib/components/chat/Chat.svelte';
	import { goto } from '$lib/navigation';
	import { getChannels } from '$lib/apis/channels';
	import { channels, config } from '$lib/stores';

	let unsubscribeChannels: (() => void) | undefined;
	let redirectingToChannel = false;

	$: directChatEnabled = $config?.features?.enable_direct_chat ?? true;

	const redirectToFirstChannel = async (value = $channels) => {
		if (($config?.features?.enable_direct_chat ?? true) !== false || redirectingToChannel) {
			return;
		}

		if (value?.[0]?.id) {
			redirectingToChannel = true;
			await goto(`/channels/${value[0].id}`);
			return;
		}

		const res = await getChannels(localStorage.token).catch(() => null);
		if (res?.length) {
			const sortedChannels = res.sort(
				(a, b) =>
					['', null, 'group', 'dm'].indexOf(a.type) - ['', null, 'group', 'dm'].indexOf(b.type)
			);
			await channels.set(sortedChannels);
			redirectingToChannel = true;
			await goto(`/channels/${sortedChannels[0].id}`);
		}
	};

	onMount(() => {
		redirectToFirstChannel();

		unsubscribeChannels = channels.subscribe((value) => {
			redirectToFirstChannel(value);
		});
	});

	onDestroy(() => {
		unsubscribeChannels?.();
	});
</script>

{#if directChatEnabled}
	<Chat chatIdProp={$page.params.id} />
{/if}
