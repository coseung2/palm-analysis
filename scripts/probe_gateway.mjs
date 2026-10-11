// One synthetic-photo integration test against isolated development resources only.
import {spawnSync} from 'node:child_process';
import {handle} from '../cloudflare/worker.mjs';
const ref='ihkbmxwidahgbrvxmrrk';
if(process.env.PALM_DEV_PROJECT_REF!==ref) throw new Error('Unexpected development ref');
const booth=crypto.randomUUID();
const endpoint=`https://api.supabase.com/v1/projects/${ref}/database/query`;
async function sql(query) {
  const response=await fetch(endpoint,{method:'POST',headers:{Authorization:`Bearer ${process.env.Supabase_access_token}`,'Content-Type':'application/json'},body:JSON.stringify({query}),signal:AbortSignal.timeout(30000)});
  if(!response.ok) throw new Error('Development test SQL failed');
  return response.json();
}
const env={PALM_ENVIRONMENT:'development',PALM_API_ENABLED:'true',PALM_AUTH_MODE:'public_booth',PALM_RUNTIME_READY:'true',PALM_BOOTH_ID:booth,PALM_SUPABASE_PROJECT_REF:ref,SUPABASE_URL:process.env.PALM_DEV_SUPABASE_URL,SUPABASE_SERVICE_KEY:process.env.PALM_DEV_SERVICE_KEY,OPERATOR_KEY:'isolated-settings-probe-key-not-a-real-secret'};
let created=null,photoKey=null;
try {
  await sql(`insert into palm_runtime.booths(id,enabled,daily_call_limit) values('${booth}',true,2)`);
  const start=await handle(new Request('https://development.test/v1/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({external_processing_consent:true})}),env);
  if(start.status!==201) throw new Error('Login-free start failed');
  created=await start.json();
  // Valid 320x320 PNG generated separately from source; no real palm or EXIF.
  const python=process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python';
  const generated=spawnSync(python,['-c',"import io,sys; from PIL import Image; b=io.BytesIO(); Image.new('RGB',(320,320),'white').save(b,'PNG'); sys.stdout.buffer.write(b.getvalue())"],{encoding:null});
  if(generated.status!==0) throw new Error('Synthetic image generation failed');
  const headers={Authorization:`Bearer ${created.access_token}`,'Content-Type':'image/png','Idempotency-Key':'synthetic-request-001'};
  const upload=await handle(new Request(`https://development.test/v1/sessions/${created.id}/analysis`,{method:'POST',headers,body:generated.stdout}),env);
  if(upload.status!==202) throw new Error('Private upload/queue registration failed');
  const repeated=await handle(new Request(`https://development.test/v1/sessions/${created.id}/analysis`,{method:'POST',headers,body:generated.stdout}),env);
  if(repeated.status!==202) throw new Error('Idempotent replay failed');
  const rows=await sql(`select photo_key,dispatched from palm_runtime.jobs where session_id='${created.id}'`);
  if(rows.length!==1 || rows[0].dispatched!==0) throw new Error('Unexpected duplicate work');
  photoKey=rows[0].photo_key;
  const cycle=spawnSync('ssh',['-o','BatchMode=yes','-o','ClearAllForwardings=yes','testauram-devspace','/opt/devspace/bin/infisical run --projectId=bde1d1c7-150c-4490-a43f-61ff9b6c6aae --env=dev --path=/ --silent -- /home/devspace/projects/palm-analysis-development/.venv/bin/python /home/devspace/projects/palm-analysis-development/scripts/run_once_worker.py'],{encoding:'utf8',timeout:180000});
  if(cycle.status!==0) throw new Error('VM consumer cycle failed');
  const view=await handle(new Request(`https://development.test/v1/sessions/${created.id}`,{headers:{Authorization:`Bearer ${created.access_token}`}}),env);
  const outcome=await view.json();
  if(outcome.status!=='failed' || outcome.error?.code!=='retake_required' || outcome.result!==null) throw new Error('Synthetic blank image must require retake');
  const final=await sql(`select j.dispatched,j.reserved,d.deleted_at is not null as deleted from palm_runtime.jobs j join palm_runtime.photo_deletions d on d.photo_key=j.photo_key where j.session_id='${created.id}'`);
  if(final[0].dispatched!==1 || final[0].reserved!==0 || !final[0].deleted) throw new Error('Quota or deletion mismatch');
  const object=await fetch(`${env.SUPABASE_URL}/storage/v1/object/palm-uploads/${photoKey}`,{headers:{apikey:env.SUPABASE_SERVICE_KEY,Authorization:`Bearer ${env.SUPABASE_SERVICE_KEY}`}});
  if(object.status===200) throw new Error('Synthetic photo still accessible after deletion');
  const denied=await handle(new Request(`https://development.test/v1/sessions/${created.id}`,{headers:{Authorization:'Bearer another-session-token'}}),env);
  if(denied.status!==404) throw new Error('Session isolation failed');
  const cancelled=await handle(new Request(`https://development.test/v1/sessions/${created.id}`,{method:'DELETE',headers:{Authorization:`Bearer ${created.access_token}`}}),env);
  if((await cancelled.json()).status!=='cancelled') throw new Error('Cancellation failed');
  console.log(JSON.stringify({login_free_start:true,private_upload:true,idempotent_job_count:1,vm_consumer:true,ocx_observation:true,synthetic_retake:true,external_call_count:1,unused_reservation_released:true,photo_deletion_confirmed:true,session_isolation:true,real_photo_sent:false,persisted_runtime_enabled:false}));
} catch(error) {
  console.error(JSON.stringify({integration_failed:true,step:error.message,credentials_suppressed:true}));
  process.exitCode=1;
} finally {
  // Only random test IDs created by this process are cleaned up; never scan/delete real rows.
  if(created) await sql(`select palm_runtime.cancel('${created.id}')`);
  await sql(`delete from palm_runtime.jobs where booth_id='${booth}'; delete from palm_runtime.sessions where booth_id='${booth}'; delete from palm_runtime.public_starts where booth_id='${booth}'; delete from palm_runtime.daily_usage where booth_id='${booth}'; delete from palm_runtime.booths where id='${booth}';`);
}
