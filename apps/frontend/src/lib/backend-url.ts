type BackendEnvironment = {
  BACKEND_INTERNAL_URL?: string;
  BACKEND_INTERNAL_HOSTPORT?: string;
};

export function backendInternalUrl(
  environment: BackendEnvironment = process.env as BackendEnvironment,
): string | null {
  const configuredUrl = environment.BACKEND_INTERNAL_URL?.trim();
  if (configuredUrl) return configuredUrl;

  const hostport = environment.BACKEND_INTERNAL_HOSTPORT?.trim();
  return hostport ? `http://${hostport}` : null;
}
