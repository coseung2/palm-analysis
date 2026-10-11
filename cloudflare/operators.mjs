const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export class OperatorError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}

export function operatorPolicy(raw) {
  let entries;
  try { entries = JSON.parse(raw); } catch { throw new OperatorError(503, 'operator_policy_required'); }
  if (!Array.isArray(entries) || !entries.length || entries.length > 100) throw new OperatorError(503, 'operator_policy_required');
  const users = new Set();
  for (const entry of entries) {
    if (!entry || typeof entry !== 'object' || Object.keys(entry).sort().join(',') !== 'booths,role,user_id' ||
        !UUID.test(entry.user_id) || users.has(entry.user_id) ||
        !['admin', 'operator'].includes(entry.role) || !Array.isArray(entry.booths) ||
        !entry.booths.length || entry.booths.length > 100 ||
        entry.booths.some(id => !UUID.test(id)) || new Set(entry.booths).size !== entry.booths.length) {
      throw new OperatorError(503, 'operator_policy_required');
    }
    users.add(entry.user_id);
  }
  return entries;
}

export async function verifyOperator(request, env) {
  const entries = operatorPolicy(env.PALM_OPERATOR_ALLOWLIST);
  const token = request.headers.get('Authorization')?.match(/^Bearer ([^\s]+)$/i)?.[1];
  if (!token || token.length > 8192) throw new OperatorError(401, 'authentication_required');
  if (!env.SUPABASE_PUBLISHABLE_KEY) throw new OperatorError(503, 'operator_auth_required');
  let response;
  try {
    response = await fetch(`${env.SUPABASE_URL}/auth/v1/user`, {
      headers: {apikey:env.SUPABASE_PUBLISHABLE_KEY, Authorization:`Bearer ${token}`},
      redirect:'error', signal:AbortSignal.timeout(10000)
    });
  } catch { throw new OperatorError(503, 'operator_auth_unavailable'); }
  if (response.status === 401 || response.status === 403) throw new OperatorError(401, 'invalid_credentials');
  if (!response.ok) throw new OperatorError(503, 'operator_auth_unavailable');
  let user;
  try { user = await response.json(); } catch { throw new OperatorError(503, 'operator_auth_unavailable'); }
  if (!user || !UUID.test(user.id) || user.is_anonymous !== false) throw new OperatorError(403, 'operator_not_allowed');
  // Only server policy controls membership; user_metadata and JWT role claims are ignored.
  const entry = entries.find(item => item.user_id === user.id);
  if (!entry) throw new OperatorError(403, 'operator_not_allowed');
  return {user_id:entry.user_id, role:entry.role, booths:[...entry.booths]};
}

export function requireBooth(actor, booth, operation) {
  if (!UUID.test(booth) || !actor.booths.includes(booth)) throw new OperatorError(403, 'booth_forbidden');
  if (!['view', 'create', 'analyze', 'cancel', 'config_get', 'config_put'].includes(operation)) throw new OperatorError(403, 'operation_forbidden');
  if (operation === 'config_put' && actor.role !== 'admin') throw new OperatorError(403, 'operation_forbidden');
}
