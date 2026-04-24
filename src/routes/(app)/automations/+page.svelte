<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import {
		createAutomation,
		deleteAutomationById,
		getAutomationItems,
		runAutomationById,
		toggleAutomationById,
		type AutomationResponse
	} from '$lib/apis/automations';
	import { config, models, showSidebar, user, WEBUI_NAME } from '$lib/stores';

	const i18n = getContext('i18n');

	let loaded = false;
	let loading = false;
	let items: AutomationResponse[] = [];
	let total = 0;
	let page = 1;
	let query = '';
	let status = 'all';

	let showCreate = false;
	let formName = '';
	let formPrompt = '';
	let formModelId = '';
	let formRrule = 'RRULE:FREQ=DAILY;INTERVAL=1';

	const canUseAutomations = () =>
		$config?.features?.enable_automations &&
		($user?.role === 'admin' || ($user?.permissions?.features?.automations ?? false));

	const loadItems = async () => {
		loading = true;
		try {
			const res = await getAutomationItems(localStorage.token, query || null, status, page);
			items = res.items ?? [];
			total = res.total ?? 0;
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			loading = false;
		}
	};

	const resetCreateForm = () => {
		formName = '';
		formPrompt = '';
		formModelId = ($models?.[0]?.id ?? '') as string;
		formRrule = 'RRULE:FREQ=DAILY;INTERVAL=1';
	};

	const createHandler = async () => {
		try {
			const created = await createAutomation(localStorage.token, {
				name: formName,
				data: {
					prompt: formPrompt,
					model_id: formModelId,
					rrule: formRrule
				}
			});
			showCreate = false;
			resetCreateForm();
			await loadItems();
			if (created?.id) {
				goto(`/automations/${created.id}`);
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const toggleHandler = async (item: AutomationResponse) => {
		try {
			const updated = await toggleAutomationById(localStorage.token, item.id);
			items = items.map((it) => (it.id === updated.id ? updated : it));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const runHandler = async (item: AutomationResponse) => {
		try {
			await runAutomationById(localStorage.token, item.id);
			toast.success($i18n.t('Automation triggered'));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	const deleteHandler = async (item: AutomationResponse) => {
		try {
			await deleteAutomationById(localStorage.token, item.id);
			items = items.filter((it) => it.id !== item.id);
			total = Math.max(0, total - 1);
			toast.success($i18n.t('Deleted {{name}}', { name: item.name }));
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(async () => {
		if (!canUseAutomations()) {
			goto('/');
			return;
		}
		resetCreateForm();
		loaded = true;
		await loadItems();
	});
</script>

<svelte:head>
	<title>{$i18n.t('Automations')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded}
	<div
		class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
		<div class="flex-1 max-h-full overflow-y-auto px-4 py-4">
			<div class="flex items-center justify-between mb-4 gap-3">
				<div>
					<div class="text-2xl font-semibold">{$i18n.t('Automations')}</div>
					<div class="text-sm text-gray-500">{total}</div>
				</div>

				<button
					class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black text-sm"
					on:click={() => (showCreate = !showCreate)}
				>
					{$i18n.t('New Automation')}
				</button>
			</div>

			<div class="grid md:grid-cols-[1fr_auto_auto] gap-2 mb-4">
				<input
					class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
					placeholder={$i18n.t('Search')}
					bind:value={query}
				/>
				<select
					class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
					bind:value={status}
				>
					<option value="all">{$i18n.t('All')}</option>
					<option value="active">{$i18n.t('Active')}</option>
					<option value="paused">{$i18n.t('Paused')}</option>
				</select>
				<button
					class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800"
					on:click={loadItems}
				>
					{$i18n.t('Refresh')}
				</button>
			</div>

			{#if showCreate}
				<div class="mb-4 rounded-2xl border border-gray-200 dark:border-gray-800 p-4 space-y-3">
					<div class="text-lg font-medium">{$i18n.t('Create Automation')}</div>
					<input
						class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
						placeholder={$i18n.t('Name')}
						bind:value={formName}
					/>
					<textarea
						class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent min-h-[8rem]"
						placeholder={$i18n.t('Prompt')}
						bind:value={formPrompt}
					></textarea>
					<select
						class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
						bind:value={formModelId}
					>
						{#each $models ?? [] as model (model.id)}
							<option value={model.id}>{model.name}</option>
						{/each}
					</select>
					<input
						class="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-transparent"
						placeholder="RRULE:FREQ=DAILY;INTERVAL=1"
						bind:value={formRrule}
					/>
					<div class="flex justify-end gap-2">
						<button class="px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800" on:click={() => (showCreate = false)}>
							{$i18n.t('Cancel')}
						</button>
						<button class="px-3 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black" on:click={createHandler}>
							{$i18n.t('Create')}
						</button>
					</div>
				</div>
			{/if}

			{#if loading}
				<div class="text-sm text-gray-500">{$i18n.t('Loading...')}</div>
			{:else if items.length === 0}
				<div class="text-sm text-gray-500">{$i18n.t('No automations found')}</div>
			{:else}
				<div class="space-y-3">
					{#each items as item (item.id)}
						<div class="rounded-2xl border border-gray-200 dark:border-gray-800 p-4">
							<div class="flex items-start justify-between gap-3">
								<div class="min-w-0">
									<a class="font-medium underline-offset-2 hover:underline" href={`/automations/${item.id}`}>
										{item.name}
									</a>
									<div class="text-xs text-gray-500 mt-1 line-clamp-2">{item.data?.prompt}</div>
									<div class="text-xs text-gray-500 mt-2">
										{item.is_active ? $i18n.t('Active') : $i18n.t('Paused')}
										· {item.data?.model_id}
									</div>
								</div>
								<div class="flex flex-wrap gap-2 justify-end">
									<button class="px-2.5 py-1.5 rounded-xl border border-gray-200 dark:border-gray-800 text-sm" on:click={() => toggleHandler(item)}>
										{item.is_active ? $i18n.t('Pause') : $i18n.t('Resume')}
									</button>
									<button class="px-2.5 py-1.5 rounded-xl border border-gray-200 dark:border-gray-800 text-sm" on:click={() => runHandler(item)}>
										{$i18n.t('Run now')}
									</button>
									<button class="px-2.5 py-1.5 rounded-xl border border-red-200 dark:border-red-900 text-sm text-red-600" on:click={() => deleteHandler(item)}>
										{$i18n.t('Delete')}
									</button>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/if}
