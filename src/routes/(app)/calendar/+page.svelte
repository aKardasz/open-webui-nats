<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import {
		createCalendar,
		createCalendarEvent,
		deleteCalendar,
		getCalendarEvents,
		getCalendars,
		type CalendarEventModel,
		type CalendarModel
	} from '$lib/apis/calendar';
	import CalendarEventModal from '$lib/components/calendar/CalendarEventModal.svelte';
	import CalendarSidebar from '$lib/components/calendar/CalendarSidebar.svelte';
	import CalendarView from '$lib/components/calendar/CalendarView.svelte';
	import { config, showSidebar, user, WEBUI_NAME } from '$lib/stores';

	const i18n = getContext('i18n');

	let loaded = false;
	let calendars: CalendarModel[] = [];
	let events: CalendarEventModel[] = [];

	let calendarName = '';
	let calendarColor = '#3b82f6';

	let selectedCalendarId = '';
	let eventTitle = '';
	let eventDescription = '';
	let eventStart = '';
	let eventEnd = '';

	const canUseCalendar = () =>
		$config?.features?.enable_calendar &&
		($user?.role === 'admin' || ($user?.permissions?.features?.calendar ?? false));

	const loadCalendarsAndEvents = async () => {
		const loadedCalendars = (await getCalendars(localStorage.token)) ?? [];
		calendars = loadedCalendars;
		if (!selectedCalendarId) {
			selectedCalendarId = loadedCalendars.find((c) => !c.is_system)?.id ?? '';
		}

		const now = new Date();
		const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
		const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 30).toISOString();
		events = (await getCalendarEvents(localStorage.token, start, end)) ?? [];
	};

	const createCalendarHandler = async () => {
		try {
			await createCalendar(localStorage.token, {
				name: calendarName,
				color: calendarColor
			});
			calendarName = '';
			await loadCalendarsAndEvents();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const deleteCalendarHandler = async (id: string) => {
		try {
			await deleteCalendar(localStorage.token, id);
			await loadCalendarsAndEvents();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const createEventHandler = async () => {
		try {
			await createCalendarEvent(localStorage.token, {
				calendar_id: selectedCalendarId,
				title: eventTitle,
				description: eventDescription || undefined,
				start_at: new Date(eventStart).getTime() * 1_000_000,
				end_at: eventEnd ? new Date(eventEnd).getTime() * 1_000_000 : undefined
			});
			eventTitle = '';
			eventDescription = '';
			await loadCalendarsAndEvents();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(async () => {
		if (!canUseCalendar()) {
			goto('/');
			return;
		}

		const now = new Date();
		const later = new Date(now.getTime() + 60 * 60 * 1000);
		eventStart = now.toISOString().slice(0, 16);
		eventEnd = later.toISOString().slice(0, 16);

		await loadCalendarsAndEvents();
		loaded = true;
	});
</script>

<svelte:head>
	<title>{$i18n.t('Calendar')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded}
	<div
		class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
			<div class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
				<div class="text-2xl font-semibold">{$i18n.t('Calendar')}</div>

				<div class="grid lg:grid-cols-2 gap-4">
					<CalendarSidebar
						{calendars}
						bind:calendarName
						bind:calendarColor
						onCreateCalendar={createCalendarHandler}
						onDeleteCalendar={deleteCalendarHandler}
					/>

					<CalendarEventModal
						{calendars}
						bind:selectedCalendarId
						bind:eventTitle
						bind:eventDescription
						bind:eventStart
						bind:eventEnd
						onCreateEvent={createEventHandler}
					/>
				</div>

				<CalendarView {events} />
			</div>
		</div>
	{/if}
