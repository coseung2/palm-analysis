import {runtimeReady} from './runtime.mjs';
import {verifyOperator, OperatorError} from './operators.mjs';
import {visitor} from './visitor.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KEY = /^[A-Za-z0-9_-]{8,128}$/;
export function reply(data, status = 200) {
  return new Response(JSON.stringify(data), {status, headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'}});
}
function fail(status, code, message) { return reply({error:{code,message,retryable:false}},status); }
export async function digest(value) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))), b=>b.toString(16).padStart(2,'0')).join('');
}
async function authorized(request, env) {
  const token = request.headers.get('Authorization')?.match(/^Bearer (.+)$/i)?.[1] || '';
  if (!env.OPERATOR_KEY || !token) return false;
  return (await digest(token)) === (await digest(env.OPERATOR_KEY));
}
async function smallJson(request) {
  if (!request.headers.get('Content-Type')?.startsWith('application/json')) throw new Error('invalid_json');
  const reader=request.body?.getReader();
  if (!reader) return {};
  let length=0; const parts=[];
  for (;;) {
    const {done,value}=await reader.read(); if(done) break;
    length+=value.length;
    if(length>16384) { await reader.cancel(); throw new Error('body_too_large'); }
    parts.push(value);
  }
  const body=new Uint8Array(length); let offset=0;
  for(const part of parts) { body.set(part,offset); offset+=part.length; }
  return JSON.parse(new TextDecoder().decode(body));
}
export function validConfig(body) {
  const allowed=['version','title','story_theme','scan_step_ms','vision_step_ms'];
  return body && Object.keys(body).length===5 && Object.keys(body).every(k=>allowed.includes(k)) &&
    Number.isInteger(body.version) && body.version>=1 && typeof body.title==='string' && body.title.trim().length>0 && body.title.length<=80 &&
    ['river','forest','stars'].includes(body.story_theme) && Number.isInteger(body.scan_step_ms) && body.scan_step_ms>=400 && body.scan_step_ms<=5000 &&
    Number.isInteger(body.vision_step_ms) && body.vision_step_ms>=600 && body.vision_step_ms<=5000;
}
async function rpc(env, op, args={}) {
  const response=await fetch(`${env.SUPABASE_URL}/rest/v1/rpc/palm_booth`, {
    method:'POST',headers:{apikey:env.SUPABASE_SERVICE_KEY,Authorization:`Bearer ${env.SUPABASE_SERVICE_KEY}`,'Content-Type':'application/json'},
    body:JSON.stringify({p_op:op,p_args:args}),signal:AbortSignal.timeout(15000)
  });
  if(!response.ok) throw new Error('database_unavailable');
  return response.json();
}
function dbReply(data, status=200) {
  const {http_status,...body}=data;
  return reply(body,http_status||status);
}
export function publicDemo(env) {
  return env.PALM_ENVIRONMENT==='demo' && env.PALM_PUBLIC_DEMO==='true' && env.PALM_AUTH_MODE!=='supabase';
}
export async function handle(request, env) {
  const {pathname}=new URL(request.url);
  if(pathname==='/health') return request.method==='GET' ? reply({status:runtimeReady(env)?'ok':'not_ready',analysis_mode:env.PALM_AUTH_MODE==='public_booth'?'ocx':'demo',demo_without_photo:env.PALM_AUTH_MODE!=='public_booth',public_sessions:env.PALM_AUTH_MODE==='public_booth'||publicDemo(env),temporary_photo_storage:env.PALM_AUTH_MODE==='public_booth',storage:'supabase'},runtimeReady(env)?200:503) : fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
  if(!pathname.startsWith('/v1/')) {
    const response=await env.ASSETS.fetch(request);
    const headers=new Headers(response.headers);
    headers.set('X-Content-Type-Options','nosniff'); headers.set('Referrer-Policy','no-referrer');
    headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
    headers.set('Permissions-Policy','camera=(self), microphone=(), geolocation=()');
    return new Response(response.body,{status:response.status,headers});
  }
  if(request.headers.get('Origin') && request.headers.get('Origin')!==new URL(request.url).origin) return fail(403,'origin_mismatch','허용되지 않는 요청 출처입니다.');
  if(!runtimeReady(env)) return fail(503,'configuration_required','부스 연결 설정이 필요합니다.');
  if(env.PALM_AUTH_MODE==='public_booth') return visitor(request,env,{reply,fail,digest,smallJson,validConfig,authorized});
  try {
    if(env.PALM_AUTH_MODE==='supabase') {
      const actor=await verifyOperator(request,env);
      if(pathname==='/v1/operator') {
        if(request.method!=='GET') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
        return reply(actor);
      }
      // Never run the legacy global RPC with an authenticated multi-booth identity.
      return fail(503,'scoped_storage_required','부스별 저장소 연결 검증이 필요합니다.');
    }
    if(pathname==='/v1/operator') {
      if(request.method!=='GET') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
      if(!await authorized(request,env)) return fail(401,'invalid_credentials','운영자 인증에 실패했습니다.');
      return reply({authorized:true,can_configure:true});
    }
    if(pathname==='/v1/config' || pathname==='/v1/sessions') {
      if(publicDemo(env) && pathname==='/v1/sessions' && request.method==='POST') {
        if(!env.PUBLIC_SESSION_LIMITER) return fail(503,'public_limit_required','체험 요청 제한 설정이 필요합니다.');
        const ip=request.headers.get('CF-Connecting-IP');
        if(!ip) return fail(403,'client_address_required','체험 연결을 확인해 주세요.');
        const limit=await env.PUBLIC_SESSION_LIMITER.limit({key:await digest(ip)});
        if(!limit.success) return fail(429,'request_limit','체험 요청이 많습니다. 잠시 후 다시 시도해 주세요.');
      }
      const publicRequest=publicDemo(env) && ((pathname==='/v1/config' && request.method==='GET') || (pathname==='/v1/sessions' && request.method==='POST'));
      if(!publicRequest && !await authorized(request,env)) return fail(401,'invalid_credentials','운영자 인증에 실패했습니다.');
      if(pathname==='/v1/config') {
        if(request.method==='GET') return dbReply(await rpc(env,'config_get'));
        if(request.method==='PUT') {
          const body=await smallJson(request);
          if(!validConfig(body)) return fail(422,'invalid_request','설정 형식을 확인해 주세요.');
          return dbReply(await rpc(env,'config_put',body));
        }
      } else if(request.method==='POST') {
        const body=await smallJson(request);
        if(!body || Object.keys(body).some(k=>k!=='external_processing_consent') || (body.external_processing_consent!==undefined && typeof body.external_processing_consent!=='boolean')) return fail(422,'invalid_request','입력 형식을 확인해 주세요.');
        const token=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
        const result=await rpc(env,'create',{id:crypto.randomUUID(),token_hash:await digest(token),consent:body.external_processing_consent||false});
        if(result.error) return dbReply(result);
        return dbReply({...result,access_token:token},201);
      }
      return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
    }
    const match=pathname.match(/^\/v1\/sessions\/([^/]+)(\/analysis)?$/);
    if(!match || !UUID.test(match[1])) return fail(404,'not_found','체험을 찾을 수 없습니다.');
    const token=request.headers.get('Authorization')?.match(/^Bearer (.+)$/i)?.[1];
    if(!token || token.length>256) return fail(401,'authentication_required','인증이 필요합니다.');
    const args={id:match[1],token_hash:await digest(token)};
    if(match[2]) {
      if(request.method!=='POST') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
      const key=request.headers.get('Idempotency-Key') || '';
      if(!KEY.test(key)) return fail(422,'invalid_request_key','요청 키를 확인해 주세요.');
      const body=await smallJson(request);
      if(!body || body.demo!==true || Object.keys(body).length!==1) return fail(422,'demo_only','현재 시연 모드에서는 사진을 업로드하지 않습니다.');
      return dbReply(await rpc(env,'demo',{...args,request_key:key}));
    }
    if(request.method==='GET') return dbReply(await rpc(env,'view',args));
    if(request.method==='DELETE') return dbReply(await rpc(env,'cancel',args));
    return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
  } catch(error) {
    if(error instanceof OperatorError) return fail(error.status,error.code,'운영자 인증 또는 부스 권한을 확인해 주세요.');
    if(error instanceof SyntaxError || error.message==='invalid_json') return fail(422,'invalid_request','JSON 입력 형식을 확인해 주세요.');
    if(error.message==='body_too_large') return fail(413,'body_too_large','요청 내용이 너무 큽니다.');
    return fail(503,'backend_unavailable','서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.');
  }
}
export default {
  fetch:handle,
  async scheduled(event, env, ctx) {
    if(runtimeReady(env) && !['supabase','public_booth'].includes(env.PALM_AUTH_MODE)) ctx.waitUntil(rpc(env,'purge'));
  }
};
