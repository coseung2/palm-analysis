-- Candidate real-analysis store. Not applied to the existing demo database.
-- All callers are trusted server processes; visitors never receive SQL access.
begin;
create schema if not exists palm_runtime;
revoke all on schema palm_runtime from public, anon, authenticated;
grant usage on schema palm_runtime to service_role;

create table palm_runtime.booths (
  id uuid primary key,
  enabled boolean not null default false,
  daily_call_limit integer not null default 0 check (daily_call_limit between 0 and 10000),
  max_pending integer not null default 2 check (max_pending between 1 and 100),
  max_running integer not null default 1 check (max_running between 1 and 8)
);
create table palm_runtime.sessions (
  id uuid primary key,
  booth_id uuid not null references palm_runtime.booths(id),
  token_hash text not null check (token_hash ~ '^[a-f0-9]{64}$'),
  consent boolean not null,
  config jsonb not null,
  expires_at timestamptz not null,
  cancelled_at timestamptz,
  created_at timestamptz not null default now()
);
create index runtime_session_expiry on palm_runtime.sessions(expires_at);
create table palm_runtime.daily_usage (
  booth_id uuid not null references palm_runtime.booths(id),
  day date not null,
  reserved integer not null default 0 check (reserved >= 0),
  dispatched integer not null default 0 check (dispatched >= 0),
  primary key (booth_id, day)
);
create table palm_runtime.jobs (
  id uuid primary key,
  session_id uuid not null references palm_runtime.sessions(id),
  booth_id uuid not null references palm_runtime.booths(id),
  request_key text not null check (request_key ~ '^[A-Za-z0-9_-]{8,128}$'),
  image_hash text not null check (image_hash ~ '^[a-f0-9]{64}$'),
  photo_key text not null unique,
  expires_at timestamptz not null,
  state text not null default 'queued' check (state in ('queued','running','completed','failed','cancelled')),
  quota_day date not null,
  reserved integer not null default 2 check (reserved between 0 and 2),
  dispatched integer not null default 0 check (dispatched between 0 and 2),
  lease_token uuid,
  lease_until timestamptz,
  result jsonb,
  error_code text,
  created_at timestamptz not null default now(),
  unique (session_id, request_key),
  check (photo_key = id::text || '.jpg'),
  check ((state='running') = (lease_token is not null and lease_until is not null))
);
create index runtime_jobs_queue on palm_runtime.jobs(created_at) where state='queued';
create index runtime_jobs_booth_state on palm_runtime.jobs(booth_id, state);
create index runtime_jobs_expiry on palm_runtime.jobs(expires_at);
create table palm_runtime.photo_deletions (
  photo_key text primary key,
  due_at timestamptz not null,
  attempts integer not null default 0 check (attempts >= 0),
  lease_token uuid,
  lease_until timestamptz,
  deleted_at timestamptz
);
create index runtime_deletion_due on palm_runtime.photo_deletions(due_at) where deleted_at is null;

alter table palm_runtime.booths enable row level security;
alter table palm_runtime.sessions enable row level security;
alter table palm_runtime.daily_usage enable row level security;
alter table palm_runtime.jobs enable row level security;
alter table palm_runtime.photo_deletions enable row level security;
revoke all on all tables in schema palm_runtime from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema palm_runtime to service_role;

create function palm_runtime.enqueue(p_id uuid, p_session uuid, p_key text, p_hash text)
returns uuid language plpgsql security invoker set search_path='' as $$
declare
  s palm_runtime.sessions%rowtype;
  b palm_runtime.booths%rowtype;
  j palm_runtime.jobs%rowtype;
  u palm_runtime.daily_usage%rowtype;
  d date := (now() at time zone 'UTC')::date;
begin
  select * into s from palm_runtime.sessions where id=p_session;
  if not found or s.cancelled_at is not null or s.expires_at<=now() or not s.consent then
    raise exception 'session_unavailable';
  end if;
  select * into b from palm_runtime.booths where id=s.booth_id for update;
  -- Same booth lock serializes enqueue, dispatch, cancellation and quota updates.
  select * into s from palm_runtime.sessions where id=p_session for update;
  if s.cancelled_at is not null or s.expires_at<=now() then raise exception 'session_unavailable'; end if;
  select * into j from palm_runtime.jobs where session_id=p_session and request_key=p_key;
  if found then
    if j.image_hash<>p_hash then raise exception 'idempotency_conflict'; end if;
    return j.id;
  end if;
  if not b.enabled then raise exception 'booth_disabled'; end if;
  if (select count(*) from palm_runtime.jobs where booth_id=b.id and state in ('queued','running'))>=b.max_pending then
    raise exception 'analysis_busy';
  end if;
  if (select count(*) from palm_runtime.jobs where session_id=p_session)>=3 then raise exception 'attempt_limit'; end if;
  if exists(select 1 from palm_runtime.jobs where session_id=p_session and state in ('queued','running','completed')) then
    raise exception 'session_busy_or_completed';
  end if;
  insert into palm_runtime.daily_usage(booth_id,day) values(b.id,d) on conflict do nothing;
  select * into u from palm_runtime.daily_usage where booth_id=b.id and day=d for update;
  if u.reserved+u.dispatched+2>b.daily_call_limit then raise exception 'quota_exhausted'; end if;
  update palm_runtime.daily_usage set reserved=reserved+2 where booth_id=b.id and day=d;
  insert into palm_runtime.jobs(id,session_id,booth_id,request_key,image_hash,photo_key,expires_at,quota_day)
    values(p_id,s.id,b.id,p_key,p_hash,p_id::text||'.jpg',least(s.expires_at,now()+interval '10 minutes'),d);
  insert into palm_runtime.photo_deletions(photo_key,due_at) values(p_id::text||'.jpg',least(s.expires_at,now()+interval '10 minutes'));
  return p_id;
end;
$$;

create function palm_runtime.claim(p_booth uuid, p_lease uuid)
returns setof palm_runtime.jobs language plpgsql security invoker set search_path='' as $$
declare b palm_runtime.booths%rowtype; target uuid;
begin
  select * into b from palm_runtime.booths where id=p_booth for update;
  if not found or not b.enabled then return; end if;
  if (select count(*) from palm_runtime.jobs where booth_id=p_booth and state='running')>=b.max_running then return; end if;
  select j.id into target from palm_runtime.jobs j join palm_runtime.sessions s on s.id=j.session_id
    where j.booth_id=p_booth and j.state='queued' and j.expires_at>now()
      and s.expires_at>now() and s.cancelled_at is null
    order by j.created_at limit 1 for update of j skip locked;
  if target is null then return; end if;
  return query update palm_runtime.jobs set state='running',lease_token=p_lease,lease_until=now()+interval '3 minutes'
    where id=target returning *;
end;
$$;

create function palm_runtime.dispatch(p_job uuid, p_lease uuid, p_stage integer)
returns boolean language plpgsql security invoker set search_path='' as $$
declare j palm_runtime.jobs%rowtype; b palm_runtime.booths%rowtype; d date:=(now() at time zone 'UTC')::date;
begin
  select * into j from palm_runtime.jobs where id=p_job;
  if not found then return false; end if;
  select * into b from palm_runtime.booths where id=j.booth_id for update;
  select * into j from palm_runtime.jobs where id=p_job for update;
  if not b.enabled or j.state<>'running' or j.lease_token<>p_lease or j.lease_until<=now() or j.expires_at<=now()
    or p_stage not in (1,2) or j.dispatched<>p_stage-1 or j.reserved<1
    or not exists(select 1 from palm_runtime.sessions where id=j.session_id and cancelled_at is null and expires_at>now()) then
    return false;
  end if;
  if j.quota_day<>d then
    insert into palm_runtime.daily_usage(booth_id,day) values(j.booth_id,d) on conflict do nothing;
    if (select reserved+dispatched+j.reserved from palm_runtime.daily_usage where booth_id=j.booth_id and day=d)>b.daily_call_limit then
      return false;
    end if;
    update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
    update palm_runtime.daily_usage set reserved=reserved+j.reserved where booth_id=j.booth_id and day=d;
    update palm_runtime.jobs set quota_day=d where id=j.id;
    j.quota_day:=d;
  end if;
  -- Dispatch records are conservative: a crash after this commit may or may not have called upstream.
  update palm_runtime.daily_usage set reserved=reserved-1,dispatched=dispatched+1
    where booth_id=j.booth_id and day=j.quota_day;
  update palm_runtime.jobs set reserved=reserved-1,dispatched=dispatched+1 where id=j.id;
  return true;
end;
$$;

create function palm_runtime.finish(p_job uuid, p_lease uuid, p_result jsonb, p_error text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare j palm_runtime.jobs%rowtype;
begin
  select * into j from palm_runtime.jobs where id=p_job;
  if not found then return false; end if;
  perform 1 from palm_runtime.booths where id=j.booth_id for update;
  select * into j from palm_runtime.jobs where id=p_job for update;
  if j.state<>'running' or j.lease_token<>p_lease or j.lease_until<=now() or j.expires_at<=now()
    or not exists(select 1 from palm_runtime.sessions where id=j.session_id and cancelled_at is null and expires_at>now()) then
    return false;
  end if;
  if (p_result is null)=(p_error is null) then raise exception 'invalid_finish'; end if;
  if p_result is not null and j.dispatched<>2 then raise exception 'stages_incomplete'; end if;
  update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
  update palm_runtime.jobs set state=case when p_error is null then 'completed' else 'failed' end,
    reserved=0,result=p_result,error_code=p_error,lease_token=null,lease_until=null where id=j.id;
  update palm_runtime.photo_deletions set due_at=least(due_at,now()) where photo_key=j.photo_key;
  return true;
end;
$$;

create function palm_runtime.cancel(p_session uuid)
returns void language plpgsql security invoker set search_path='' as $$
declare s palm_runtime.sessions%rowtype; j palm_runtime.jobs%rowtype;
begin
  select * into s from palm_runtime.sessions where id=p_session;
  if not found then return; end if;
  perform 1 from palm_runtime.booths where id=s.booth_id for update;
  update palm_runtime.sessions set cancelled_at=coalesce(cancelled_at,now()) where id=s.id;
  for j in select * from palm_runtime.jobs where session_id=s.id for update loop
    update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
    update palm_runtime.jobs set state='cancelled',reserved=0,result=null,error_code=null,lease_token=null,lease_until=null where id=j.id;
    update palm_runtime.photo_deletions set due_at=least(due_at,now()) where photo_key=j.photo_key;
  end loop;
end;
$$;

create function palm_runtime.recover(p_booth uuid)
returns integer language plpgsql security invoker set search_path='' as $$
declare j palm_runtime.jobs%rowtype; n integer:=0;
begin
  perform 1 from palm_runtime.booths where id=p_booth for update;
  for j in select * from palm_runtime.jobs where booth_id=p_booth and state in ('queued','running')
    and (expires_at<=now() or (state='running' and lease_until<=now())
      or not exists(select 1 from palm_runtime.sessions s where s.id=session_id and s.cancelled_at is null and s.expires_at>now())) for update loop
    if j.expires_at>now() and j.dispatched=0 and exists(select 1 from palm_runtime.sessions s where s.id=j.session_id and s.cancelled_at is null and s.expires_at>now()) then
      update palm_runtime.jobs set state='queued',lease_token=null,lease_until=null where id=j.id;
    else
      update palm_runtime.daily_usage set reserved=reserved-j.reserved where booth_id=j.booth_id and day=j.quota_day;
      update palm_runtime.jobs set state='failed',reserved=0,error_code=case when expires_at<=now() then 'expired' else 'interrupted_unknown' end,
        lease_token=null,lease_until=null where id=j.id;
      update palm_runtime.photo_deletions set due_at=least(due_at,now()) where photo_key=j.photo_key;
    end if;
    n:=n+1;
  end loop;
  return n;
end;
$$;
create function palm_runtime.claim_deletion(p_lease uuid)
returns setof palm_runtime.photo_deletions language plpgsql security invoker set search_path='' as $$
declare target text;
begin
  select photo_key into target from palm_runtime.photo_deletions
    where deleted_at is null and due_at<=now() and (lease_until is null or lease_until<=now())
    order by due_at limit 1 for update skip locked;
  if target is null then return; end if;
  return query update palm_runtime.photo_deletions set lease_token=p_lease,lease_until=now()+interval '1 minute'
    where photo_key=target returning *;
end;
$$;
create function palm_runtime.finish_deletion(p_key text,p_lease uuid,p_success boolean)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
  update palm_runtime.photo_deletions set attempts=attempts+1,
    deleted_at=case when p_success then now() else null end,
    due_at=case when p_success then due_at else now()+interval '1 minute' end,
    lease_token=null,lease_until=null
    where photo_key=p_key and deleted_at is null and lease_token=p_lease and lease_until>now();
  return found;
end;
$$;
revoke all on all functions in schema palm_runtime from public, anon, authenticated;
grant execute on all functions in schema palm_runtime to service_role;
commit;
