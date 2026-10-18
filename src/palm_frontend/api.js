export async function api(path, options = {}, token = '') {
  const response = await fetch(path, {
    ...options,
    signal: options.signal || AbortSignal.timeout(45000),
    headers: {...options.headers, ...(token ? {Authorization: `Bearer ${token}`} : {})},
  });
  if (!response.headers.get('Content-Type')?.includes('application/json')) {
    throw new Error('연결을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || '요청을 완료하지 못했습니다.');
  return data;
}

export function json(body) {
  return {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
}
