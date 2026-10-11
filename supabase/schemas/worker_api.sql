-- Service-only PostgREST bridge into the private runtime schema.
begin;
create function public.palm_worker(p_op text,p_args jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path='' as $$
declare result jsonb;
begin
  if p_op='booths' then
    select coalesce(jsonb_agg(id),'[]') into result from palm_runtime.booths where enabled;
    return result;
  elsif p_op='claim' then
    select to_jsonb(j)||jsonb_build_object('config',s.config) into result
      from palm_runtime.claim((p_args->>'booth')::uuid,(p_args->>'lease')::uuid) j
      join palm_runtime.sessions s on s.id=j.session_id;
    return result;
  elsif p_op='dispatch' then
    return to_jsonb(palm_runtime.dispatch((p_args->>'job')::uuid,(p_args->>'lease')::uuid,(p_args->>'stage')::integer));
  elsif p_op='finish' then
    return to_jsonb(palm_runtime.finish((p_args->>'job')::uuid,(p_args->>'lease')::uuid,p_args->'result',p_args->>'error'));
  elsif p_op='recover' then
    return to_jsonb(palm_runtime.recover((p_args->>'booth')::uuid));
  elsif p_op='claim_deletion' then
    select to_jsonb(d) into result from palm_runtime.claim_deletion((p_args->>'lease')::uuid) d;
    return result;
  elsif p_op='finish_deletion' then
    return to_jsonb(palm_runtime.finish_deletion(p_args->>'photo_key',(p_args->>'lease')::uuid,(p_args->>'success')::boolean));
  end if;
  raise exception 'unknown_operation';
end;
$$;
revoke all on function public.palm_worker(text,jsonb) from public,anon,authenticated;
grant execute on function public.palm_worker(text,jsonb) to service_role;
commit;
