export function canSelectMultipleModels(role: string | null | undefined): boolean {
	return role === 'admin';
}

export function normalizeSelectedModelsForRole(
	selectedModels: string[] | null | undefined,
	role: string | null | undefined
): string[] {
	const models = selectedModels?.length ? selectedModels : [''];

	if (canSelectMultipleModels(role)) {
		return models;
	}

	return [models.find((modelId) => modelId !== '') ?? ''];
}
