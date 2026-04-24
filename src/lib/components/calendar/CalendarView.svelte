<script lang="ts">
	import { getContext } from 'svelte';
	import type { CalendarEventModel } from '$lib/apis/calendar';

	const i18n = getContext('i18n');

	export let events: CalendarEventModel[] = [];
</script>

<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4">
	<div class="text-lg font-medium mb-3">{$i18n.t('Upcoming Events')}</div>
	{#if events.length === 0}
		<div class="text-sm text-gray-500">{$i18n.t('No events found')}</div>
	{:else}
		<div class="space-y-2">
			{#each events as event (event.instance_id ?? event.id)}
				<div class="rounded-xl border border-gray-100 dark:border-gray-900 p-3">
					<div class="font-medium">{event.title}</div>
					<div class="text-sm text-gray-500 mt-1">{event.description}</div>
					<div class="text-xs text-gray-500 mt-2">
						{new Date(event.start_at / 1_000_000).toLocaleString()}
					</div>
					{#if event.meta?.automation_id}
						<div class="text-xs text-purple-500 mt-1">
							{$i18n.t('Scheduled task')}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
