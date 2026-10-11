import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {PGlite} from '@electric-sql/pglite';
const booth='11111111-1111-4111-8111-111111111111';
const session='22222222-2222-4222-8222-222222222222';
const job='33333333-3333-4333-8333-333333333333';
const lease='44444444-4444-4444-8444-444444444444';
const hash='a'.repeat(64);
async function setup(limit=8) {
  const db=new PGlite();
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
  await db.exec(await readFile(new URL('../supabase/schemas/jobs.sql',import.meta.url),'utf8'));
  await db.exec(await readFile(new URL('../supabase/schemas/worker_api.sql',import.meta.url),'utf8'));
  await db.exec(await readFile(new URL('../supabase/schemas/visitor_api.sql',import.meta.url),'utf8'));
  await db.query('insert into palm_runtime.booths(id,enabled,daily_call_limit) values($1,true,$2)',[booth,limit]);
  await db.query("insert into palm_runtime.sessions(id,booth_id,token_hash,consent,config,expires_at) values($1,$2,$3,true,'{}',now()+interval '1 hour')",[session,booth,hash]);
  await db.exec('set role service_role');
  return db;
}
async function enqueue(db,id=job,key='request-001',digest=hash) {
  return (await db.query('select palm_runtime.enqueue($1,$2,$3,$4) as id',[id,session,key,digest])).rows[0].id;
}
async function claim(db,token=lease) {
  return (await db.query('select * from palm_runtime.claim($1,$2)',[booth,token])).rows;
}
async function dispatch(db,stage=1,token=lease) {
  return (await db.query('select palm_runtime.dispatch($1,$2,$3) as allowed',[job,token,stage])).rows[0].allowed;
}
const options={};
test('enqueue reserves two calls exactly once and rejects a conflicting image',options,async()=>{
  const db=await setup();
  try {
    assert.equal(await enqueue(db),job);
    assert.equal(await enqueue(db),job);
    assert.deepEqual((await db.query('select reserved,dispatched from palm_runtime.daily_usage')).rows,[{reserved:2,dispatched:0}]);
    await assert.rejects(enqueue(db,job,'request-001','b'.repeat(64)),/idempotency_conflict/);
    assert.equal((await db.query('select count(*) as n from palm_runtime.jobs')).rows[0].n,1);
  } finally {await db.close();}
});
test('quota exhaustion rejects before a job or reservation is written',options,async()=>{
  const db=await setup(1);
  try {
    await assert.rejects(enqueue(db),/quota_exhausted/);
    assert.equal((await db.query('select count(*) as n from palm_runtime.jobs')).rows[0].n,0);
    assert.equal((await db.query('select count(*) as n from palm_runtime.daily_usage')).rows[0].n,0);
  } finally {await db.close();}
});
test('claim and phase dispatch are fenced and do not duplicate calls',options,async()=>{
  const db=await setup();
  try {
    await enqueue(db); assert.equal((await claim(db)).length,1); assert.equal((await claim(db)).length,0);
    assert.equal(await dispatch(db,2),false);
    assert.equal(await dispatch(db,1,'55555555-5555-4555-8555-555555555555'),false);
    assert.equal(await dispatch(db,1),true); assert.equal(await dispatch(db,1),false);
    assert.equal(await dispatch(db,2),true); assert.equal(await dispatch(db,2),false);
    assert.deepEqual((await db.query('select reserved,dispatched from palm_runtime.daily_usage')).rows,[{reserved:0,dispatched:2}]);
    assert.equal((await db.query("select palm_runtime.finish($1,$2,'{}',null) as ok",[job,lease])).rows[0].ok,true);
    assert.equal((await db.query("select palm_runtime.finish($1,$2,'{}',null) as ok",[job,lease])).rows[0].ok,false);
  } finally {await db.close();}
});
test('cancel releases only unused reservations and rejects late result',options,async()=>{
  const db=await setup();
  try {
    await enqueue(db); await claim(db); await dispatch(db);
    await db.query('select palm_runtime.cancel($1)',[session]);
    await db.query('select palm_runtime.cancel($1)',[session]);
    assert.equal((await db.query("select palm_runtime.finish($1,$2,'{}',null) as ok",[job,lease])).rows[0].ok,false);
    assert.deepEqual((await db.query('select reserved,dispatched from palm_runtime.daily_usage')).rows,[{reserved:0,dispatched:1}]);
    assert.deepEqual((await db.query('select state,result,lease_token from palm_runtime.jobs')).rows,[{state:'cancelled',result:null,lease_token:null}]);
    assert.equal((await db.query('select due_at<=now() as due from palm_runtime.photo_deletions')).rows[0].due,true);
    await assert.rejects(enqueue(db),/session_unavailable/);
  } finally {await db.close();}
});
test('recovery requeues only before dispatch; ambiguous external call is not retried',options,async()=>{
  const db=await setup();
  try {
    await enqueue(db); await claim(db);
    await db.query("update palm_runtime.jobs set lease_until=now()-interval '1 second'");
    await db.query('select palm_runtime.recover($1)',[booth]);
    assert.equal((await db.query('select state from palm_runtime.jobs')).rows[0].state,'queued');
    const newer='55555555-5555-4555-8555-555555555555';
    await claim(db,newer); assert.equal(await dispatch(db,1,lease),false);
    assert.equal(await dispatch(db,1,newer),true);
    await db.query("update palm_runtime.jobs set lease_until=now()-interval '1 second'");
    await db.query('select palm_runtime.recover($1)',[booth]);
    assert.equal((await db.query('select error_code from palm_runtime.jobs')).rows[0].error_code,'interrupted_unknown');
    assert.equal((await claim(db,newer)).length,0);
    assert.deepEqual((await db.query('select reserved,dispatched from palm_runtime.daily_usage')).rows,[{reserved:0,dispatched:1}]);
  } finally {await db.close();}
});
test('dispatch enforces current UTC day and a disabled booth blocks calls',options,async()=>{
  const db=await setup();
  try {
    await enqueue(db); await claim(db);
    await db.query("update palm_runtime.daily_usage set day=day-1");
    await db.query("update palm_runtime.jobs set quota_day=quota_day-1");
    await db.query('update palm_runtime.booths set daily_call_limit=1');
    assert.equal(await dispatch(db),false);
    await db.query('update palm_runtime.booths set daily_call_limit=2');
    assert.equal(await dispatch(db),true);
    const rows=(await db.query('select reserved,dispatched from palm_runtime.daily_usage order by day')).rows;
    assert.deepEqual(rows,[{reserved:0,dispatched:0},{reserved:1,dispatched:1}]);
    await db.query('update palm_runtime.booths set enabled=false');
    assert.equal(await dispatch(db,2),false);
  } finally {await db.close();}
});
test('photo deletion retries with a lease and records actual success only',options,async()=>{
  const db=await setup();
  try {
    await enqueue(db); await db.query('select palm_runtime.cancel($1)',[session]);
    const claim=()=>db.query('select * from palm_runtime.claim_deletion($1)',[lease]);
    assert.equal((await claim()).rows.length,1); assert.equal((await claim()).rows.length,0);
    const finish=success=>db.query('select palm_runtime.finish_deletion($1,$2,$3) as ok',[job+'.jpg',lease,success]);
    assert.equal((await finish(false)).rows[0].ok,true);
    assert.equal((await db.query('select deleted_at from palm_runtime.photo_deletions')).rows[0].deleted_at,null);
    assert.equal((await claim()).rows.length,0);
    await db.query("update palm_runtime.photo_deletions set due_at=now()-interval '1 second'");
    assert.equal((await claim()).rows.length,1);
    assert.equal((await finish(true)).rows[0].ok,true);
    assert.equal((await finish(true)).rows[0].ok,false);
    assert.equal((await db.query('select attempts,deleted_at is not null as deleted from palm_runtime.photo_deletions')).rows[0].attempts,2);
    assert.equal((await claim()).rows.length,0);
  } finally {await db.close();}
});
test('visitor upload is quota-reserved but cannot be consumed before storage is ready',options,async()=>{
  const db=await setup();
  try {
    const rpc=(op,args)=>db.query('select public.palm_visitor($1,$2) as data',[op,JSON.stringify({booth,id:session,token_hash:hash,...args})]);
    const first=(await rpc('prepare',{job,request_key:'request-001',image_hash:hash})).rows[0].data;
    assert.equal(first.upload_required,true); assert.equal((await claim(db)).length,0);
    const repeated=(await rpc('prepare',{job,request_key:'request-001',image_hash:hash})).rows[0].data;
    assert.equal(repeated.upload_required,false);
    await assert.rejects(rpc('view',{token_hash:'b'.repeat(64)}),/session_not_found/);
    await rpc('ready',{job}); assert.equal((await claim(db)).length,1);
    await rpc('cancel',{}); assert.equal(await dispatch(db),false);
  } finally {await db.close();}
});
test('expired upload is released, deleted, and not requeued',options,async()=>{
  const db=await setup();
  try {
    await db.query('select public.palm_visitor($1,$2)',['prepare',JSON.stringify({booth,id:session,token_hash:hash,job,request_key:'request-001',image_hash:hash})]);
    await db.query("update palm_runtime.jobs set expires_at=now()-interval '1 second'");
    await db.query('select public.palm_maintenance()');
    assert.deepEqual((await db.query('select state,reserved,error_code from palm_runtime.jobs')).rows,[{state:'failed',reserved:0,error_code:'upload_expired'}]);
    assert.equal((await db.query('select due_at<=now() as due from palm_runtime.photo_deletions')).rows[0].due,true);
  } finally {await db.close();}
});
test('browser roles have neither schema usage nor execute access',options,async()=>{
  const db=await setup();
  try {
    await db.exec('reset role');
    for(const role of ['anon','authenticated']) {
      await db.exec('set role '+role);
      await assert.rejects(db.query('select * from palm_runtime.jobs'),/permission denied/);
      await assert.rejects(db.query('select palm_runtime.claim($1,$2)',[booth,lease]),/permission denied/);
      await db.exec('reset role');
    }
    const rows=(await db.query("select relrowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='palm_runtime' and relkind='r'")).rows;
    assert.equal(rows.length,6); assert.ok(rows.every(row=>row.relrowsecurity));
  } finally {await db.close();}
});
