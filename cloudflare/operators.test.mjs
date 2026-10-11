import test from 'node:test';
import assert from 'node:assert/strict';
import {operatorPolicy, verifyOperator, requireBooth, OperatorError} from './operators.mjs';

const user='12345678-1234-4234-8234-123456789abc';
const booth='87654321-1234-4234-8234-123456789abc';
const other='aaaaaaaa-1234-4234-8234-123456789abc';
const entry={user_id:user,role:'operator',booths:[booth]};
const env={SUPABASE_URL:'https://aaaaaaaaaaaaaaaaaaaa.supabase.co',SUPABASE_PUBLISHABLE_KEY:'test-only-public-key',PALM_OPERATOR_ALLOWLIST:JSON.stringify([entry])};
const request=new Request('https://booth.test/v1/operator',{headers:{Authorization:'Bearer test-only-access-token'}});
function fails(code) { return error => error instanceof OperatorError && error.code === code; }

test('policy refuses absent, malformed, wildcard and duplicate membership',()=>{
  for (const raw of [undefined,'{}','[]','invalid',JSON.stringify([{...entry,role:'owner'}]),JSON.stringify([{...entry,booths:['*']}]),JSON.stringify([entry,entry]),JSON.stringify([{...entry,booths:[booth,booth]}]),JSON.stringify([{...entry,extra:true}])]) {
    assert.throws(()=>operatorPolicy(raw),fails('operator_policy_required'));
  }
  assert.deepEqual(operatorPolicy(env.PALM_OPERATOR_ALLOWLIST),[entry]);
});
test('missing token does not call Auth',async(t)=>{
  t.mock.method(globalThis,'fetch',async()=>{throw new Error('unexpected call');});
  await assert.rejects(verifyOperator(new Request('https://booth.test/v1/operator'),env),fails('authentication_required'));
  assert.equal(globalThis.fetch.mock.callCount(),0);
});
test('server verifies user and ignores editable metadata',async(t)=>{
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    assert.equal(url,env.SUPABASE_URL+'/auth/v1/user');
    assert.equal(options.headers.apikey,env.SUPABASE_PUBLISHABLE_KEY);
    assert.equal(options.redirect,'error');
    return Response.json({id:user,is_anonymous:false,user_metadata:{role:'admin',booths:[other]}});
  });
  const actor=await verifyOperator(request,env);
  assert.deepEqual(actor,entry);
  assert.throws(()=>requireBooth(actor,other,'view'),fails('booth_forbidden'));
  assert.throws(()=>requireBooth(actor,booth,'config_put'),fails('operation_forbidden'));
  for(const op of ['view','create','analyze','cancel','config_get']) assert.doesNotThrow(()=>requireBooth(actor,booth,op));
});
test('unknown, anonymous and malformed users cannot become operators',async(t)=>{
  for(const body of [{id:other,is_anonymous:false,user_metadata:{role:'admin'}},{id:user,is_anonymous:true},{id:user},{id:'bad-id',is_anonymous:false},null]) {
    t.mock.method(globalThis,'fetch',async()=>Response.json(body));
    await assert.rejects(verifyOperator(request,env),fails('operator_not_allowed'));
  }
});
test('expired tokens and Auth failures fail closed',async(t)=>{
  for(const [status,code] of [[401,'invalid_credentials'],[403,'invalid_credentials'],[429,'operator_auth_unavailable'],[500,'operator_auth_unavailable']]) {
    t.mock.method(globalThis,'fetch',async()=>new Response('{}',{status}));
    await assert.rejects(verifyOperator(request,env),fails(code));
  }
  t.mock.method(globalThis,'fetch',async()=>{throw new Error('private network details');});
  await assert.rejects(verifyOperator(request,env),fails('operator_auth_unavailable'));
  t.mock.method(globalThis,'fetch',async()=>new Response('not json'));
  await assert.rejects(verifyOperator(request,env),fails('operator_auth_unavailable'));
});
test('server-side policy revocation takes effect on next request',async(t)=>{
  t.mock.method(globalThis,'fetch',async()=>Response.json({id:user,is_anonymous:false}));
  await verifyOperator(request,env);
  await assert.rejects(verifyOperator(request,{...env,PALM_OPERATOR_ALLOWLIST:JSON.stringify([{...entry,user_id:other}])}),fails('operator_not_allowed'));
});
test('admins are still limited to explicit booths',()=>{
  const actor={...entry,role:'admin'};
  assert.doesNotThrow(()=>requireBooth(actor,booth,'config_put'));
  assert.throws(()=>requireBooth(actor,other,'config_put'),fails('booth_forbidden'));
  assert.throws(()=>requireBooth(actor,booth,'unknown'),fails('operation_forbidden'));
});
