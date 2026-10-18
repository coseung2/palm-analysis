export function isServiceReady(health) {
  return health?.status === 'ok' && ['ocx', 'claude'].includes(health.analysis_mode) &&
    health.public_sessions === true && health.demo_without_photo !== true;
}

export function requireRealResult(result) {
  const text = value => typeof value === 'string' && value.trim().length > 0;
  const names = ['life', 'heart', 'head', 'fate'];
  if (!result || result.is_demo !== false || !['ocx', 'claude'].includes(result.mode) ||
      !Array.isArray(result.lines) || result.lines.length !== 4 ||
      !names.every(name => result.lines.filter(line => line?.name === name).length === 1) ||
      !result.lines.every(line => text(line.trait) && text(line.description) && text(line.reading) &&
        ['visible', 'unclear', 'not_visible'].includes(line.visibility)) ||
      !Array.isArray(result.visions) || result.visions.length < 1 || result.visions.length > 5 ||
      !result.visions.every(text) || !text(result.disclaimer)) {
    throw new Error('이야기를 불러오지 못했습니다. 다시 촬영해 주세요.');
  }
  return result;
}
