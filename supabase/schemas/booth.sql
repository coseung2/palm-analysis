-- Server-only booth storage. Browser roles never receive table or RPC access.
begin;
create table if not exists public.palm_booth_config (
  id smallint primary key check (id = 1),
  settings jsonb not null
);
insert into public.palm_booth_config values (1, '{"version":1,"title":"오늘의 손금","story_theme":"river","scan_step_ms":1600,"vision_step_ms":1900}') on conflict do nothing;
create table if not exists public.palm_booth_sessions (
  id uuid primary key,
  token_hash text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '1 hour',
  status text not null default 'awaiting_image' check (status in ('awaiting_image','completed','cancelled')),
  config jsonb not null,
  consent boolean not null default false,
  attempts integer not null default 0 check (attempts between 0 and 3),
  request_key text,
  result jsonb
);
create index if not exists palm_booth_expiry_idx on public.palm_booth_sessions (expires_at);
alter table public.palm_booth_config enable row level security;
alter table public.palm_booth_sessions enable row level security;
revoke all on public.palm_booth_config, public.palm_booth_sessions from public, anon, authenticated;
grant select, insert, update, delete on public.palm_booth_config, public.palm_booth_sessions to service_role;

create or replace function public.palm_booth(p_op text, p_args jsonb default '{}')
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  cfg jsonb;
  s public.palm_booth_sessions%rowtype;
  result_json jsonb;
  lines_json jsonb;
  theme_text text;
  err jsonb;
begin
  -- All operations share a short transaction lock. Limits and versions stay atomic.
  select settings into cfg from public.palm_booth_config where id=1 for update;
  delete from public.palm_booth_sessions where expires_at <= now();
  if p_op = 'purge' then return '{"status":"ok"}'; end if;
  if p_op = 'config_get' then return cfg; end if;
  if p_op = 'config_put' then
    if (p_args->>'version')::integer <> (cfg->>'version')::integer then
      return jsonb_build_object('http_status',409,'error',jsonb_build_object('code','config_conflict','message','설정이 변경되었습니다. 운영자 연결을 다시 해 주세요.','retryable',false));
    end if;
    cfg := p_args || jsonb_build_object('version',(cfg->>'version')::integer+1);
    update public.palm_booth_config set settings=cfg where id=1;
    return cfg;
  end if;
  if p_op = 'create' then
    if (select count(*) from public.palm_booth_sessions) >= 500 then
      return jsonb_build_object('http_status',429,'error',jsonb_build_object('code','session_limit','message','부스가 혼잡합니다. 잠시 후 다시 시도해 주세요.','retryable',true));
    end if;
    insert into public.palm_booth_sessions(id,token_hash,config,consent)
    values ((p_args->>'id')::uuid,p_args->>'token_hash',cfg,coalesce((p_args->>'consent')::boolean,false)) returning * into s;
  else
    select * into s from public.palm_booth_sessions where id=(p_args->>'id')::uuid and token_hash=p_args->>'token_hash';
    if not found then
      return jsonb_build_object('http_status',404,'error',jsonb_build_object('code','session_not_found','message','체험이 만료되었거나 접근할 수 없습니다.','retryable',false));
    end if;
    if p_op='cancel' then
      update public.palm_booth_sessions set status='cancelled',result=null,request_key=null where id=s.id returning * into s;
    elsif p_op='demo' then
      if s.status='cancelled' then
        return jsonb_build_object('http_status',409,'error',jsonb_build_object('code','session_cancelled','message','취소된 체험입니다.','retryable',false));
      end if;
      if s.status='completed' and s.request_key<>p_args->>'request_key' then
        return jsonb_build_object('http_status',409,'error',jsonb_build_object('code','session_completed','message','새 체험을 시작해 주세요.','retryable',false));
      end if;
      if s.status<>'completed' then
        select jsonb_agg(jsonb_build_object('name',name,'visibility','unclear','trait','시연 예시 · 실제 검출 아님','description','사진은 업로드하거나 분석하지 않았습니다. 부스 연결 확인용 예시입니다.','reading','시연용 문구입니다. 실제 손금 해석은 보류합니다.')) into lines_json from unnest(array['life','head','heart','fate']) as name;
        theme_text := case s.config->>'story_theme' when 'forest' then '숲 사이로 따뜻한 빛이 스며듭니다.' when 'stars' then '별 아래에서 길을 찾는 장면을 상상합니다.' else '강가에 작은 불빛이 떠오릅니다.' end;
        result_json := jsonb_build_object('mode','demo','is_demo',true,'hand','unknown','lines',lines_json,'visions',jsonb_build_array('지금부터는 오락용으로 만든 전생 이야기입니다.',theme_text,'이야기가 걷히고 지금의 손으로 돌아옵니다.'),'disclaimer','손금 해석과 전생 이야기는 오락용 창작이며, 건강·수명·미래에 대한 사실 판단이 아닙니다.','config_version',s.config->'version');
        update public.palm_booth_sessions set result=result_json,status='completed',attempts=attempts+1,request_key=p_args->>'request_key' where id=s.id returning * into s;
      end if;
    elsif p_op<>'view' then raise exception 'Unknown operation';
    end if;
  end if;
  return jsonb_build_object('id',s.id,'status',s.status,'created_at',extract(epoch from s.created_at),'expires_at',extract(epoch from s.expires_at),'external_processing_consent',s.consent,'attempts',s.attempts,'config',s.config,'result',s.result,'error',null);
end;
$$;
revoke all on function public.palm_booth(text,jsonb) from public, anon, authenticated;
grant execute on function public.palm_booth(text,jsonb) to service_role;
commit;
