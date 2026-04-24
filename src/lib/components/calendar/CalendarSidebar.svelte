<script lang="ts">
	import { getContext } from 'svelte';
	import type { CalendarModel } from '$lib/apis/calendar';

	const i18n = getContext('i18n');

	export let calendars: CalendarModel[] = [];
	export let calendarName = '';
	export let calendarColor = '#3b82f6';
	export let onCreateCalendar: () => void = () => {};
	export let onDeleteCalendar: (id: string) => void = () => {};
</script>

<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4 space-y-3">
	<div class="text-lg font-medium">{$i18n.t('Calendars')}</div>
	<div class="flex gap-2">
		<input
			class="flex-1 px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
			placeholder={$i18n.t('Calendar name')}
			bind:value={calendarName}
		/>
		<input type="color" bind:value={calendarColor} class="h-10 w-12 rounded-xl border border-gray-200 dark:border-gray-800" />
		<button class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black" on:click={onCreateCalendar}>
			{$i18n.t('Create')}
		</button>
	</div>

	<div class="space-y-2">
		{#each calendars as cal (cal.id)}
			<div class="rounded-xl border border-gray-100 dark:border-gray-900 p-3 flex items-center justify-between gap-3">
				<div class="flex items-center gap-2 min-w-0">
					<div class="size-3 rounded-full" style={`background:${cal.color ?? '#3b82f6'}`}></div>
					<div class="truncate">{cal.name}</div>
				</div>
				{#if !cal.is_default && !cal.is_system}
					<button class="px-2.5 py-1.5 rounded-xl border border-red-200 dark:border-red-900 text-red-600 text-sm" on:click={() => onDeleteCalendar(cal.id)}>
						{$i18n.t('Delete')}
					</button>
				{/if}
			</div>
		{/each}
	</div>
</div>
