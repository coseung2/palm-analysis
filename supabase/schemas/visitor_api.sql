-- Login-free visitor API, invoked only by the trusted Worker service key.
begin;
alter table palm_runtime.booths add column config jsonb not null default '{"version":1,"title":"오늘의 손금","story_theme":"river","scan_step_ms":1600,"vision_step_ms":1900}';
alter table palm_runtime.jobs drop constraint jobs_state_check;
alter table palm_runtime.jobs add constraint jobs_state_check check(state in ('uploading','queued','running','completed','failed','cancelled'));
create table palm_runtime.public_starts (
  booth_id uuid not null references palm_runtime.booths(id),
  minute timestamptz not null, starts integer not null check(starts>0), primary key(booth_id,minute)
);
alter table palm_runtime.public_starts enable row level security;
revoke all on palm_runtime.public_starts from public,anon,authenticated;
grant select,insert,update,delete on palm_runtime.public_starts to service_role;

create function palm_runtime.session_view(p_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
select jsonb_build_object('id',s.id,'created_at',extract(epoch from s.created_at),'expires_at',extract(epoch from s.expires_at),
  'external_processing_consent',s.consent,'config',s.config,
  'status',case when s.cancelled_at is not null then 'cancelled' when j.state='completed' then 'completed'
    when j.state='failed' then 'failed' when j.state is not null then 'analyzing' else 'awaiting_image' end,
  'attempts',(select count(*) from palm_runtime.jobs where session_id=s.id),'result',j.result,
  'error',case when j.error_code is not null then jsonb_build_object('code',j.error_code,
    'message',case when j.error_code='retake_required' then '손바닥이 선명하게 보이도록 다시 촬영해 주세요.' else '분석을 완료하지 못했습니다. 다시 촬영해 주세요.' end,
    'retryable',j.error_code in ('retake_required','provider_busy','provider_unavailable','analysis_timeout')) else null end)
from palm_runtime.sessions s left join lateral (select * from palm_runtime.jobs where session_id=s.id order by created_at desc,id desc limit 1) j on true
where s.id=p_id;
$$;

create function public.palm_visitor(p_op text,p_args jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path='' as $$
declare b palm_runtime.booths%rowtype; s palm_runtime.sessions%rowtype; j palm_runtime.jobs%rowtype;
  target uuid; m timestamptz:=date_trunc('minute',now()); count_starts integer; updated jsonb;
begin
  select * into b from palm_runtime.booths where id=(p_args->>'booth')::uuid for update;
  if not found or not b.enabled then raise exception 'booth_disabled'; end if;
  if p_op='config_get' then return b.config; end if;
  if p_op='config_put' then
    updated:=p_args->'config';
    if (updated->>'version')::integer<>(b.config->>'version')::integer then raise exception 'config_conflict'; end if;
    updated:=updated||jsonb_build_object('version',(b.config->>'version')::integer+1);
    update palm_runtime.booths set config=updated where id=b.id;
    return updated;
  end if;
  if p_op='create' then
    if coalesce((p_args->>'consent')::boolean,false) is not true then raise exception 'consent_required'; end if;
    delete from palm_runtime.public_starts where minute<now()-interval '2 minutes';
    select starts into count_starts from palm_runtime.public_starts where booth_id=b.id and minute=m;
    if coalesce(count_starts,0)>=6 then raise exception 'request_limit'; end if;
    if (select count(*) from palm_runtime.sessions where booth_id=b.id and expires_at>now() and cancelled_at is null)>=500 then raise exception 'session_limit'; end if;
    insert into palm_runtime.public_starts values(b.id,m,1) on conflict(booth_id,minute) do update set starts=palm_runtime.public_starts.starts+1;
    insert into palm_runtime.sessions(id,booth_id,token_hash,consent,config,expires_at)
      values((p_args->>'id')::uuid,b.id,p_args->>'token_hash',true,b.config,now()+interval '1 hour') returning * into s;
    return palm_runtime.session_view(s.id);
  end if;
  select * into s from palm_runtime.sessions where id=(p_args->>'id')::uuid and booth_id=b.id and token_hash=p_args->>'token_hash' and expires_at>now() for update;
  if not found then raise exception 'session_not_found'; end if;
  if p_op='view' then return palm_runtime.session_view(s.id); end if;
  if p_op='cancel' then perform palm_runtime.cancel(s.id); return palm_runtime.session_view(s.id); end if;
  if s.cancelled_at is not null then raise exception 'session_cancelled'; end if;
  if p_op='prepare' then
    select * into j from palm_runtime.jobs where session_id=s.id and request_key=p_args->>'request_key';
    if found then
      if j.image_hash<>p_args->>'image_hash' then raise exception 'idempotency_conflict'; end if;
      return jsonb_build_object('upload_required',false,'job',j.id,'view',palm_runtime.session_view(s.id));
    end if;
    if exists(select 1 from palm_runtime.jobs where session_id=s.id and state='uploading') then raise exception 'session_busy_or_completed'; end if;
    if (select count(*) from palm_runtime.jobs where booth_id=b.id and state in ('uploading','queued','running'))>=b.max_pending then raise exception 'analysis_busy'; end if;
    target:=palm_runtime.enqueue((p_args->>'job')::uuid,s.id,p_args->>'request_key',p_args->>'image_hash');
    update palm_runtime.jobs set state='uploading' where id=target;
    return jsonb_build_object('upload_required',true,'job',target,'view',palm_runtime.session_view(s.id));
  end if;
  select * into j from palm_runtime.jobs where id=(p_args->>'job')::uuid and session_id=s.id for update;
  if not found then raise exception 'job_not_found'; end if;
  if p_op='ready' and j.state='uploading' and j.expires_at>now() then
    update palm_runtime.jobs set state='queued' where id=j.id;
    return palm_runtime.session_view(s.id);
  elsif p_op='upload_failed' and j.state='uploading' then
    update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
    update palm_runtime.jobs set state='failed',reserved=0,error_code='upload_failed' where id=j.id;
    update palm_runtime.photo_deletions set due_at=least(due_at,now()) where photo_key=j.photo_key;
    return palm_runtime.session_view(s.id);
  end if;
  raise exception 'job_not_ready';
end;
$$;

create function palm_runtime.expire_uploads(p_booth uuid)
returns void language plpgsql security invoker set search_path='' as $$
declare j palm_runtime.jobs%rowtype;
begin
  perform 1 from palm_runtime.booths where id=p_booth for update;
  for j in select * from palm_runtime.jobs where booth_id=p_booth and state='uploading' and expires_at<=now() for update loop
    update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
    update palm_runtime.jobs set state='failed',reserved=0,error_code='upload_expired' where id=j.id;
    update palm_runtime.photo_deletions set due_at=least(due_at,now()) where photo_key=j.photo_key;
  end loop;
end;
$$;
create function public.palm_reschedule_photo(p_job uuid)
returns void language sql security invoker set search_path='' as $$
update palm_runtime.photo_deletions set due_at=now(),deleted_at=null,lease_token=null,lease_until=null where photo_key=p_job::text||'.jpg';
$$;
revoke all on function public.palm_reschedule_photo(uuid) from public,anon,authenticated;
grant execute on function public.palm_reschedule_photo(uuid) to service_role;

-- Repeat absence checks through the upload window: a timed-out remote upload may arrive late.
alter table palm_runtime.photo_deletions add column verify_until timestamptz not null default now()+interval '11 minutes';
create or replace function palm_runtime.claim_deletion(p_lease uuid)
returns setof palm_runtime.photo_deletions language plpgsql security invoker set search_path='' as $$
declare target text;
begin
  select photo_key into target from palm_runtime.photo_deletions
    where (deleted_at is null or verify_until>now()) and due_at<=now() and (lease_until is null or lease_until<=now())
    order by due_at limit 1 for update skip locked;
  if target is null then return; end if;
  return query update palm_runtime.photo_deletions set lease_token=p_lease,lease_until=now()+interval '1 minute'
    where photo_key=target returning *;
end;
$$;
create or replace function palm_runtime.finish_deletion(p_key text,p_lease uuid,p_success boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
  update palm_runtime.photo_deletions set attempts=attempts+1,
    deleted_at=case when p_success then now() else null end,due_at=now()+interval '1 minute',
    lease_token=null,lease_until=null
    where photo_key=p_key and lease_token=p_lease and lease_until>now();
  return found;
end;
$$;

create function public.palm_maintenance()
returns void language plpgsql security invoker set search_path='' as $$
declare b record; s record;
begin
  for b in select id from palm_runtime.booths order by id loop
    perform palm_runtime.expire_uploads(b.id);
    perform palm_runtime.recover(b.id);
  end loop;
  for s in select id from palm_runtime.sessions where expires_at<=now() loop
    perform palm_runtime.cancel(s.id);
    delete from palm_runtime.jobs where session_id=s.id;
    delete from palm_runtime.sessions where id=s.id;
  end loop;
  delete from palm_runtime.daily_usage where day<(now() at time zone 'UTC')::date-30 and reserved=0;
  delete from palm_runtime.photo_deletions where deleted_at<now()-interval '1 hour';
end;
$$;
revoke all on function public.palm_maintenance() from public,anon,authenticated;
grant execute on function public.palm_maintenance() to service_role;
revoke all on all functions in schema palm_runtime from public,anon,authenticated;
grant execute on all functions in schema palm_runtime to service_role;
revoke all on function public.palm_visitor(text,jsonb) from public,anon,authenticated;
grant execute on function public.palm_visitor(text,jsonb) to service_role;
commit;
