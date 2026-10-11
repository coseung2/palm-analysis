const ENVIRONMENTS = new Set(['demo', 'development', 'staging', 'production']);
const PROJECT_REF = /^[a-z]{20}$/;
const DEMO_PROJECT_REF = 'pyugqoogcoynvywihgym';

export function runtimeReady(env) {
  if (!ENVIRONMENTS.has(env.PALM_ENVIRONMENT) || env.PALM_API_ENABLED !== 'true') return false;
  // Production stays closed until operator login and booth isolation are implemented.
  if (env.PALM_ENVIRONMENT === 'production') return false;
  if (!PROJECT_REF.test(env.PALM_SUPABASE_PROJECT_REF || '')) return false;
  if (env.PALM_ENVIRONMENT !== 'demo' && env.PALM_SUPABASE_PROJECT_REF === DEMO_PROJECT_REF) return false;
  if (!env.SUPABASE_SERVICE_KEY) return false;
  const authMode = env.PALM_AUTH_MODE || 'operator_key';
  if (authMode === 'operator_key') {
    if (env.PALM_ENVIRONMENT !== 'demo' || !env.OPERATOR_KEY) return false;
  } else if (authMode === 'public_booth') {
    if (env.PALM_ENVIRONMENT !== 'development' || !env.OPERATOR_KEY || env.PALM_RUNTIME_READY !== 'true' || !env.PALM_BOOTH_ID) return false;
  } else if (authMode === 'supabase') {
    if (!env.SUPABASE_PUBLISHABLE_KEY || !env.PALM_OPERATOR_ALLOWLIST) return false;
  } else return false;
  return env.SUPABASE_URL === `https://${env.PALM_SUPABASE_PROJECT_REF}.supabase.co`;
}
