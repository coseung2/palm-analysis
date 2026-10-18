import {api, json} from './api.js';

export function createSessionClient() {
  let current = null;
  let creating = null;

  return {
    get current() { return current; },
    async open(consent) {
      if (current) return current;
      const request = api('/v1/sessions', {method: 'POST', ...json({external_processing_consent: consent})});
      creating = request;
      try {
        current = await request;
        return current;
      } finally {
        if (creating === request) creating = null;
      }
    },
    close() {
      const pending = creating;
      creating = null;
      const known = current;
      current = null;
      return Promise.resolve(known || (pending ? pending.catch(() => null) : null)).then(created => {
        if (!created) return;
        return api(`/v1/sessions/${created.id}`, {method: 'DELETE'}, created.access_token).catch(error => {
          current = created;
          throw error;
        });
      });
    },
    remember(view) { current = {...current, ...view}; return current; },
    forget() { current = null; },
  };
}
