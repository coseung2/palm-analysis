import test from 'node:test';
import assert from 'node:assert/strict';
import worker, {handle, validConfig, digest} from './worker.mjs';
import {runtimeReady} from './runtime.mjs';

const env={PALM_ENVIRONMENT:'demo',PALM_API_ENABLED:'true',PALM_SUPABASE_PROJECT_REF:'aaaaaaaaaaaaaaaaaaaa',SUPABASE_URL:'https://aaaaaaaaaaaaaaaaaaaa.supabase.co',SUPABASE_SERVICE_KEY:'server-test-key',OPERATOR_KEY:'test-only-not-a-real-operator-secret'};
const auth={Authorization:`Bearer ${env.OPERATOR_KEY}`,'Content-Type':'application/json'};

test('health labels demo without photo upload',async()=>{
  const response=await handle(new Request('https://booth.test/health'),env);
  const data=await response.json(); assert.equal(data.demo_without_photo,true); assert.equal(data.analysis_mode,'demo');
});
test('runtime requires explicit enabled environment and matching project',()=>{
  assert.equal(runtimeReady(env),true);
  for(const patch of [
    {PALM_ENVIRONMENT:undefined}, {PALM_ENVIRONMENT:'unknown'},
    {PALM_API_ENABLED:undefined}, {PALM_API_ENABLED:'false'}, {PALM_API_ENABLED:true},
    {PALM_SUPABASE_PROJECT_REF:undefined}, {PALM_SUPABASE_PROJECT_REF:'bad-ref'},
    {SUPABASE_URL:'https://bbbbbbbbbbbbbbbbbbbb.supabase.co'},
    {SUPABASE_URL:'http://aaaaaaaaaaaaaaaaaaaa.supabase.co'},
    {SUPABASE_URL:env.SUPABASE_URL+'/rest/v1'},
    {SUPABASE_SERVICE_KEY:''}, {OPERATOR_KEY:''},
    {PALM_ENVIRONMENT:'production'}
  ]) assert.equal(runtimeReady({...env,...patch}),false,JSON.stringify(Object.keys(patch)));
});
test('existing demo project cannot be reused for development or staging',()=>{
  const demo={...env,PALM_SUPABASE_PROJECT_REF:'pyugqoogcoynvywihgym',SUPABASE_URL:'https://pyugqoogcoynvywihgym.supabase.co'};
  assert.equal(runtimeReady({...demo,PALM_ENVIRONMENT:'demo'}),true);
  assert.equal(runtimeReady({...demo,PALM_ENVIRONMENT:'development'}),false);
  assert.equal(runtimeReady({...demo,PALM_ENVIRONMENT:'staging'}),false);
});
test('unconfigured health and API fail closed without database access',async(t)=>{
  let calls=0;
  t.mock.method(globalThis,'fetch',async()=>{calls++; throw new Error('unexpected database call');});
  for(const patch of [{PALM_API_ENABLED:'false'},{PALM_ENVIRONMENT:'production'}, {SUPABASE_URL:'https://wrong.test'}]) {
    const blocked={...env,...patch};
    const health=await handle(new Request('https://booth.test/health'),blocked);
    assert.equal(health.status,503); assert.equal((await health.json()).status,'not_ready');
    for(const path of ['/v1/config','/v1/sessions','/v1/sessions/12345678-1234-4234-8234-123456789abc']) {
      const response=await handle(new Request('https://booth.test'+path,{headers:auth}),blocked);
      assert.equal(response.status,503);
      assert.equal((await response.json()).error.code,'configuration_required');
    }
    await worker.scheduled({},blocked,{waitUntil(){throw new Error('unexpected cron task');}});
  }
  assert.equal(calls,0);
});
test('enabled environment can run scheduled cleanup',async(t)=>{
  t.mock.method(globalThis,'fetch',async()=>new Response('{}'));
  let task;
  await worker.scheduled({},env,{waitUntil(value){task=value;}});
  await task;
  assert.ok(task instanceof Promise);
  assert.equal(globalThis.fetch.mock.callCount(),1);
});
test('Supabase identity endpoint validates login but never reaches legacy booth storage',async(t)=>{
  const actor={user_id:'12345678-1234-4234-8234-123456789abc',role:'operator',booths:['87654321-1234-4234-8234-123456789abc']};
  const secured={...env,PALM_ENVIRONMENT:'development',PALM_AUTH_MODE:'supabase',SUPABASE_PUBLISHABLE_KEY:'test-public-key',PALM_OPERATOR_ALLOWLIST:JSON.stringify([actor]),OPERATOR_KEY:undefined};
  assert.equal(runtimeReady(secured),true);
  assert.equal(runtimeReady({...secured,PALM_AUTH_MODE:'operator_key',OPERATOR_KEY:'legacy-test-key'}),false);
  t.mock.method(globalThis,'fetch',async url=>{
    assert.equal(url,env.SUPABASE_URL+'/auth/v1/user');
    return Response.json({id:actor.user_id,is_anonymous:false});
  });
  const headers={Authorization:'Bearer test-access-token'};
  const identity=await handle(new Request('https://booth.test/v1/operator',{headers}),secured);
  assert.equal(identity.status,200); assert.deepEqual(await identity.json(),actor);
  const blocked=await handle(new Request('https://booth.test/v1/config',{headers}),secured);
  assert.equal(blocked.status,503); assert.equal((await blocked.json()).error.code,'scoped_storage_required');
  await worker.scheduled({},secured,{waitUntil(){throw new Error('legacy purge must not run');}});
  assert.equal((await handle(new Request('https://booth.test/v1/operator'),secured)).status,401);
});
test('public demo permits start without key but keeps settings and session access protected',async(t)=>{
  const open={...env,PALM_PUBLIC_DEMO:'true',PUBLIC_SESSION_LIMITER:{async limit(){return {success:true};}}};
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    const {p_op}=JSON.parse(options.body);
    if(p_op==='config_get') return Response.json({version:1,title:'시연'});
    if(p_op==='create') return Response.json({id:'12345678-1234-4234-8234-123456789abc',status:'awaiting_image'});
    throw new Error('unexpected RPC');
  });
  assert.equal((await handle(new Request('https://booth.test/v1/config'),open)).status,200);
  const created=await handle(new Request('https://booth.test/v1/sessions',{method:'POST',headers:{'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.1'},body:'{}'}),open);
  assert.equal(created.status,201); assert.equal(typeof (await created.json()).access_token,'string');
  assert.equal((await handle(new Request('https://booth.test/v1/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:'{}'}),open)).status,401);
  assert.equal((await handle(new Request('https://booth.test/v1/sessions/12345678-1234-4234-8234-123456789abc'),open)).status,401);
});
test('public creation fails closed on missing or exhausted limiter',async()=>{
  const open={...env,PALM_PUBLIC_DEMO:'true'};
  const request=()=>new Request('https://booth.test/v1/sessions',{method:'POST',headers:{'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.1'},body:'{}'});
  assert.equal((await handle(request(),open)).status,503);
  assert.equal((await handle(request(),{...open,PUBLIC_SESSION_LIMITER:{async limit(){return {success:false};}}})).status,429);
});
test('protected config refuses missing credentials',async()=>{
  assert.equal((await handle(new Request('https://booth.test/v1/config'),env)).status,401);
});
test('cross-origin API requests denied',async()=>{
  assert.equal((await handle(new Request('https://booth.test/v1/config',{headers:{Origin:'https://other.test'}}),env)).status,403);
});
test('config validates ranges, types and extra fields',()=>{
  const c={version:1,title:'오늘의 손금',story_theme:'river',scan_step_ms:1600,vision_step_ms:1900};
  assert.equal(validConfig(c),true); assert.equal(validConfig({...c,version:'1'}),false);
  assert.equal(validConfig({...c,scan_step_ms:0}),false); assert.equal(validConfig({...c,extra:true}),false);
});
test('demo endpoint refuses an actual image',async()=>{
  const request=new Request('https://booth.test/v1/sessions/12345678-1234-4234-8234-123456789abc/analysis',{method:'POST',headers:{Authorization:'Bearer session-test-token','Content-Type':'image/png','Idempotency-Key':'request-001'},body:new Uint8Array([1,2,3])});
  assert.equal((await handle(request,env)).status,422);
});
test('invalid config cannot reach database',async()=>{
  const response=await handle(new Request('https://booth.test/v1/config',{method:'PUT',headers:auth,body:'{}'}),env);
  assert.equal(response.status,422);
});
test('session token hashes are not plaintext',async()=>{
  const value=await digest('session-token'); assert.equal(value.length,64); assert.notEqual(value,'session-token');
});
test('malformed JSON gives safe error',async()=>{
  const response=await handle(new Request('https://booth.test/v1/sessions',{method:'POST',headers:auth,body:'{' }),env);
  assert.equal(response.status,422); assert.equal((await response.json()).error.code,'invalid_request');
});
