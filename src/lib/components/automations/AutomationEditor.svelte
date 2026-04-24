<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import {
		deleteAutomationById,
		getAutomationRuns,
		runAutomationById,
		toggleAutomationById,
		updateAutomationById,
		type AutomationResponse,
		type AutomationRunModel
	} from '$lib/apis/automations';
	import { models } from '$lib/stores';

	const i18n = getContext('i18n');

	export let automation: AutomationResponse;

	let runs: AutomationRunModel[] = [];
	let name = '';
	let prompt = '';
	let modelId = '';
	let rrule = '';
	let isActive = true;

	const loadRuns = async () => {
		runs = (await getAutomationRuns(localStorage.token, automation.id)) ?? [];
	};

	const saveHandler = async () => {
		try {
			const updated = await updateAutomationById(localStorage.token, automation.id, {
				name,
				data: {
					prompt,
					model_id: modelId,
					rrule
				},
				is_active: isActive
			});
			automation = updated;
			isActive = updated.is_active;
			toast.success($i18n.t('Automation updated'));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const toggleHandler = async () => {
		try {
			const updated = await toggleAutomationById(localStorage.token, automation.id);
			automation = updated;
			isActive = updated.is_active;
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const runHandler = async () => {
		try {
			await runAutomationById(localStorage.token, automation.id);
			toast.success($i18n.t('Automation triggered'));
			await loadRuns();
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const deleteHandler = async () => {
		try {
			await deleteAutomationById(localStorage.token, automation.id);
			goto('/automations');
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(async () => {
		name = automation.name;
		prompt = automation.data?.prompt ?? '';
		modelId = automation.data?.model_id ?? '';
		rrule = automation.data?.rrule ?? '';
		isActive = automation.is_active;
		await loadRuns();
	});
</script>

<div class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
	<div class="flex items-center justify-between gap-3">
		<div class="flex items-center gap-3">
			<button class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800" on:click={() => goto('/automations')}>
				{$i18n.t('Back')}
			</button>
			<div class="text-2xl font-semibold">{automation.name}</div>
		</div>
		<div class="flex gap-2">
			<button class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800" on:click={toggleHandler}>
				{isActive ? $i18n.t('Pause') : $i18n.t('Resume')}
			</button>
			<button class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800" on:click={runHandler}>
				{$i18n.t('Run now')}
			</button>
			<button class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black" on:click={saveHandler}>
				{$i18n.t('Save')}
			</button>
		</div>
	</div>

	<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4 space-y-3">
		<input class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={name} />
		<textarea
			class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent min-h-[10rem]"
			bind:value={prompt}
		></textarea>
		<select class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={modelId}>
			{#each $models ?? [] as model (model.id)}
				<option value={model.id}>{model.name}</option>
			{/each}
		</select>
		<input class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent" bind:value={rrule} />
		<label class="flex items-center gap-2 text-sm">
			<input type="checkbox" bind:checked={isActive} />
			{$i18n.t('Active')}
		</label>
		<div class="flex justify-end">
			<button class="px-3 py-2 rounded-xl border border-red-200 dark:border-red-900 text-red-600" on:click={deleteHandler}>
				{$i18n.t('Delete')}
			</button>
		</div>
	</div>

	<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4">
		<div class="text-lg font-medium mb-3">{$i18n.t('Runs')}</div>
		{#if runs.length === 0}
			<div class="text-sm text-gray-500">{$i18n.t('No runs yet')}</div>
		{:else}
			<div class="space-y-2">
				{#each runs as run (run.id)}
					<div class="rounded-xl border border-gray-100 dark:border-gray-900 p-3 text-sm">
						<div class="font-medium">{run.status}</div>
						<div class="text-gray-500">{run.chat_id ?? 'No chat'}</div>
						{#if run.error}
							<div class="text-red-500 mt-1">{run.error}</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
