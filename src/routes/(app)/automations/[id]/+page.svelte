<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';

	import {
		getAutomationById,
		type AutomationResponse
	} from '$lib/apis/automations';
	import { models, showSidebar, user, config, WEBUI_NAME } from '$lib/stores';
	import AutomationEditor from '$lib/components/automations/AutomationEditor.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let automation: AutomationResponse | null = null;

	const canUseAutomations = () =>
		$config?.features?.enable_automations &&
		($user?.role === 'admin' || ($user?.permissions?.features?.automations ?? false));
	$: automationId = $page.params.id;

	const loadAutomation = async () => {
		try {
			const res = await getAutomationById(localStorage.token, automationId);
			if (!res) {
				goto('/automations');
				return;
			}
			automation = res;
			loaded = true;
		} catch (e) {
			toast.error(`${e}`);
			goto('/automations');
		}
	};

	onMount(async () => {
		if (!canUseAutomations()) {
			goto('/');
			return;
		}
		await loadAutomation();
	});
</script>

<svelte:head>
	<title>{automation?.name || $i18n.t('Automation')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if loaded && automation}
	<div
		class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
		<AutomationEditor {automation} />
	</div>
{/if}
