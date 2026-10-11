import test from 'node:test';
import assert from 'node:assert/strict';
import {handle} from './worker.mjs';
const booth='11111111-1111-4111-8111-111111111111';
const session='22222222-2222-4222-8222-222222222222';
const job='33333333-3333-4333-8333-333333333333';
const env={PALM_ENVIRONMENT:'development',PALM_API_ENABLED:'true',PALM_AUTH_MODE:'public_booth',PALM_RUNTIME_READY:'true',PALM_BOOTH_ID:booth,PALM_SUPABASE_PROJECT_REF:'ihkbmxwidahgbrvxmrrk',SUPABASE_URL:'https://ihkbmxwidahgbrvxmrrk.supabase.co',SUPABASE_SERVICE_KEY:'test-service',OPERATOR_KEY:'test-settings-key'};
const analysis=body=>new Request(`https://booth.test/v1/sessions/${session}/analysis`,{method:'POST',headers:{Authorization:'Bearer test-session-token','Content-Type':'image/png','Idempotency-Key':'request-001'},body});
test('login-free real mode requires explicit readiness and consent',async(t)=>{
  const health=await handle(new Request('https://booth.test/health'),env);
  assert.equal((await health.json()).analysis_mode,'ocx');
  const disabled=await handle(new Request('https://booth.test/v1/sessions',{method:'POST'}),{...env,PALM_RUNTIME_READY:'false'});
  assert.equal(disabled.status,503);
  t.mock.method(globalThis,'fetch',async()=>{throw new Error('unexpected remote call');});
  const response=await handle(new Request('https://booth.test/v1/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),env);
  assert.equal(response.status,422);
  assert.equal((await handle(new Request('https://booth.test/v1/config',{method:'PUT'}),env)).status,401);
});
test('public config access is not proof of settings permission',async()=>{
  const wrong=new Request('https://booth.test/v1/operator',{headers:{Authorization:'Bearer wrong'}});
  assert.equal((await handle(wrong,env)).status,401);
  const correct=new Request('https://booth.test/v1/operator',{headers:{Authorization:'Bearer '+env.OPERATOR_KEY}});
  assert.equal((await handle(correct,env)).status,200);
});
test('visitor upload reserves before private storage and publishes queue readiness afterwards',async(t)=>{
  const operations=[];
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    if(url.includes('/storage/')) {
      operations.push('private-upload');
      assert.equal(options.headers['x-upsert'],'false'); assert.equal(options.headers.Authorization,'Bearer test-service');
      return Response.json({}, {status:200});
    }
    const payload=JSON.parse(options.body); operations.push(payload.p_op);
    assert.equal(payload.p_args.booth,booth);
    if(payload.p_op==='prepare') return Response.json({upload_required:true,job});
    return Response.json({id:session,status:'analyzing'});
  });
  const response=await handle(analysis(new Uint8Array([1,2,3])),env);
  assert.equal(response.status,202);
  assert.deepEqual(operations,['view','prepare','private-upload','ready']);
});
test('repeated analysis does not upload or create another work item',async(t)=>{
  let uploads=0;
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    if(url.includes('/storage/')) uploads++;
    const payload=JSON.parse(options.body);
    return Response.json(payload.p_op==='prepare'?{upload_required:false,job,view:{status:'analyzing'}}:{status:'analyzing'});
  });
  assert.equal((await handle(analysis(new Uint8Array([1])),env)).status,202); assert.equal(uploads,0);
});
test('failed private upload schedules deletion and never marks queue ready',async(t)=>{
  const ops=[];
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    if(url.includes('/storage/')) return Response.json({}, {status:503});
    const payload=JSON.parse(options.body); ops.push(payload.p_op||'reschedule');
    if(payload.p_op==='prepare') return Response.json({upload_required:true,job});
    return Response.json({status:'failed'});
  });
  assert.equal((await handle(analysis(new Uint8Array([1])),env)).status,503);
  assert.deepEqual(ops,['view','prepare','reschedule','upload_failed']);
});
test('database isolation and quota errors are safe and stop before storage',async(t)=>{
  t.mock.method(globalThis,'fetch',async()=>Response.json({message:'session_not_found',private:'do-not-show'}, {status:400}));
  const response=await handle(analysis(new Uint8Array([1])),env);
  assert.equal(response.status,404); assert.ok(!(await response.text()).includes('do-not-show'));
});
