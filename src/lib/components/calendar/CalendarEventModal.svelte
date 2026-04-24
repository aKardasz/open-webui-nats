<script lang="ts">
	import { getContext } from 'svelte';
	import type { CalendarModel } from '$lib/apis/calendar';

	const i18n = getContext('i18n');

	export let calendars: CalendarModel[] = [];
	export let selectedCalendarId = '';
	export let eventTitle = '';
	export let eventDescription = '';
	export let eventStart = '';
	export let eventEnd = '';
	export let onCreateEvent: () => void = () => {};
</script>

<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4 space-y-3">
	<div class="text-lg font-medium">{$i18n.t('New Event')}</div>
	<select class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={selectedCalendarId}>
		{#each calendars.filter((c) => !c.is_system) as cal (cal.id)}
			<option value={cal.id}>{cal.name}</option>
		{/each}
	</select>
	<input class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" placeholder={$i18n.t('Title')} bind:value={eventTitle} />
	<textarea
		class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent min-h-[6rem]"
		placeholder={$i18n.t('Description')}
		bind:value={eventDescription}
	></textarea>
	<input type="datetime-local" class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={eventStart} />
	<input type="datetime-local" class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={eventEnd} />
	<div class="flex justify-end">
		<button class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black" on:click={onCreateEvent}>
			{$i18n.t('Create')}
		</button>
	</div>
</div>
