const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KEY=/^[A-Za-z0-9_-]{8,128}$/;
const ERRORS={session_not_found:404,session_cancelled:409,idempotency_conflict:409,config_conflict:409,consent_required:422,request_limit:429,session_limit:429,quota_exhausted:429,attempt_limit:429,analysis_busy:429,session_busy_or_completed:409,booth_disabled:503};

export async function visitor(request,env,{reply,fail,digest,smallJson,validConfig,authorized}) {
  const path=new URL(request.url).pathname;
  const headers={apikey:env.SUPABASE_SERVICE_KEY,Authorization:`Bearer ${env.SUPABASE_SERVICE_KEY}`,'Content-Type':'application/json'};
  async function remote(name,body) {
    const response=await fetch(`${env.SUPABASE_URL}/rest/v1/rpc/${name}`,{method:'POST',headers,body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    const value=await response.json();
    if(!response.ok) {
      const code=Object.keys(ERRORS).find(code=>value.message===code);
      const error=new Error(code||'backend_unavailable'); error.status=ERRORS[code]||503; throw error;
    }
    return value;
  }
  const rpc=(op,args={})=>remote('palm_visitor',{p_op:op,p_args:{...args,booth:env.PALM_BOOTH_ID}});
  try {
    if(!UUID.test(env.PALM_BOOTH_ID||'') || env.PALM_RUNTIME_READY!=='true') return fail(503,'configuration_required','부스가 아직 준비되지 않았습니다.');
    if(path==='/v1/operator') {
      if(request.method!=='GET') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
      if(!await authorized(request,env)) return fail(401,'invalid_credentials','설정 변경 권한이 필요합니다.');
      return reply({authorized:true,can_configure:true});
    }
    if(path==='/v1/config') {
      if(request.method==='GET') return reply(await rpc('config_get'));
      if(request.method==='PUT') {
        if(!await authorized(request,env)) return fail(401,'invalid_credentials','설정 변경 권한이 필요합니다.');
        const config=await smallJson(request);
        if(!validConfig(config)) return fail(422,'invalid_request','설정 형식을 확인해 주세요.');
        return reply(await rpc('config_put',{config}));
      }
      return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
    }
    if(path==='/v1/sessions') {
      if(request.method!=='POST') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
      const body=await smallJson(request);
      if(!body || Object.keys(body).some(k=>k!=='external_processing_consent') || body.external_processing_consent!==true) return fail(422,'consent_required','사진의 외부 처리 안내에 동의해 주세요.');
      const token=Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,'0')).join('');
      return reply({...await rpc('create',{id:crypto.randomUUID(),token_hash:await digest(token),consent:true}),access_token:token},201);
    }
    const match=path.match(/^\/v1\/sessions\/([^/]+)(\/analysis)?$/);
    if(!match || !UUID.test(match[1])) return fail(404,'not_found','체험을 찾을 수 없습니다.');
    const token=request.headers.get('Authorization')?.match(/^Bearer ([^\s]+)$/i)?.[1];
    if(!token || token.length>256) return fail(401,'authentication_required','체험 접근 정보가 필요합니다.');
    const args={id:match[1],token_hash:await digest(token)};
    if(!match[2]) {
      if(request.method==='GET') return reply(await rpc('view',args));
      if(request.method==='DELETE') return reply(await rpc('cancel',args));
      return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
    }
    if(request.method!=='POST') return fail(405,'method_not_allowed','허용되지 않는 요청입니다.');
    const key=request.headers.get('Idempotency-Key')||'';
    if(!KEY.test(key)) return fail(422,'invalid_request_key','요청 키를 확인해 주세요.');
    const type=request.headers.get('Content-Type');
    if(!['image/jpeg','image/png','image/webp'].includes(type)) return fail(415,'unsupported_image','JPEG, PNG, WebP만 사용할 수 있습니다.');
    await rpc('view',args);
    const reader=request.body?.getReader();
    if(!reader) return fail(422,'invalid_image','사진이 필요합니다.');
    let length=0; const parts=[];
    for(;;) {
      const {done,value}=await reader.read(); if(done) break;
      length+=value.length;
      if(length>5242880) {await reader.cancel(); return fail(413,'body_too_large','5 MiB 이하 사진을 사용해 주세요.');}
      parts.push(value);
    }
    if(!length) return fail(422,'invalid_image','사진이 필요합니다.');
    const bytes=new Uint8Array(length); let offset=0;
    for(const part of parts) {bytes.set(part,offset); offset+=part.length;}
    const image_hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
    const prepared=await rpc('prepare',{...args,job:crypto.randomUUID(),request_key:key,image_hash});
    if(!prepared.upload_required) return reply(prepared.view,prepared.view.status==='analyzing'?202:200);
    if(!UUID.test(prepared.job)) throw new Error('backend_unavailable');
    try {
      const upload=await fetch(`${env.SUPABASE_URL}/storage/v1/object/palm-uploads/${prepared.job}.jpg`,{
        method:'POST',headers:{apikey:env.SUPABASE_SERVICE_KEY,Authorization:`Bearer ${env.SUPABASE_SERVICE_KEY}`,'Content-Type':type,'x-upsert':'false'},
        body:bytes,signal:AbortSignal.timeout(30000)
      });
      if(!upload.ok) throw new Error('upload_failed');
      return reply(await rpc('ready',{...args,job:prepared.job}),202);
    } catch(error) {
      // Fence deletion completion again after a cancelled or ambiguous late upload.
      await remote('palm_reschedule_photo',{p_job:prepared.job});
      try {await rpc('upload_failed',{...args,job:prepared.job});} catch {}
      throw error;
    }
  } catch(error) {
    if(error instanceof SyntaxError || error.message==='invalid_json') return fail(422,'invalid_request','입력 형식을 확인해 주세요.');
    if(error.message==='body_too_large') return fail(413,'body_too_large','요청 내용이 너무 큽니다.');
    return fail(error.status||503,error.status?error.message:'backend_unavailable','부스 요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
}
