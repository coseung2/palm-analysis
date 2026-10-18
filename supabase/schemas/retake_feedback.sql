-- Additive revision: preserve bounded retake feedback without storing photos or logs.
begin;
alter table palm_runtime.jobs add column retake_reason text
  check (retake_reason is null or char_length(retake_reason) between 1 and 300);

create or replace function public.palm_worker(p_op text,p_args jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path='' as $$
declare result jsonb; accepted boolean;
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
    accepted:=palm_runtime.finish((p_args->>'job')::uuid,(p_args->>'lease')::uuid,p_args->'result',p_args->>'error');
    if accepted and p_args->>'error'='retake_required' then
      update palm_runtime.jobs set retake_reason=nullif(left(btrim(p_args->>'retake_reason'),300),'') where id=(p_args->>'job')::uuid;
    end if;
    return to_jsonb(accepted);
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

create or replace function palm_runtime.session_view(p_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
select jsonb_build_object('id',s.id,'created_at',extract(epoch from s.created_at),'expires_at',extract(epoch from s.expires_at),
  'external_processing_consent',s.consent,'config',s.config,
  'status',case when s.cancelled_at is not null then 'cancelled' when j.state='completed' then 'completed'
    when j.state='failed' then 'failed' when j.state is not null then 'analyzing' else 'awaiting_image' end,
  'attempts',(select count(*) from palm_runtime.jobs where session_id=s.id),'result',j.result,
  'error',case when s.cancelled_at is null and j.error_code is not null then jsonb_build_object('code',j.error_code,
    'message',case when j.error_code='retake_required' then coalesce(j.retake_reason,'손바닥이 선명하게 보이도록 다시 촬영해 주세요.') else '분석을 완료하지 못했습니다. 다시 촬영해 주세요.' end,
    'retryable',j.error_code in ('retake_required','provider_busy','provider_unavailable','analysis_timeout')) else null end)
from palm_runtime.sessions s left join lateral (select * from palm_runtime.jobs where session_id=s.id order by created_at desc,id desc limit 1) j on true
where s.id=p_id;
$$;
revoke all on function palm_runtime.session_view(uuid) from public,anon,authenticated;
grant execute on function palm_runtime.session_view(uuid) to service_role;
commit;
