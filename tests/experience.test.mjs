import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {isServiceReady, requireRealResult} from '../src/palm_frontend/contract.js';

const health={status:'ok',analysis_mode:'ocx',public_sessions:true};
const result=()=>({
  mode:'ocx',is_demo:false,
  lines:['life','heart','head','fate'].map(name=>({name,visibility:'unclear',trait:'불명확',description:'선이 보이지 않습니다.',reading:'해석을 보류합니다.'})),
  visions:['테스트용 응답 구조'],disclaimer:'오락용 해석입니다.'
});

test('visitor starts only against a ready real analysis service',()=>{
  assert.equal(isServiceReady(health),true);
  assert.equal(isServiceReady({...health,analysis_mode:'claude'}),true);
  for(const patch of [{analysis_mode:'demo'},{analysis_mode:undefined},{status:'not_ready'},{public_sessions:false},{public_sessions:undefined},{demo_without_photo:true}]){
    assert.equal(isServiceReady({...health,...patch}),false);
  }
  assert.equal(isServiceReady(null),false);
});

test('product rejects example results and incomplete narratives',()=>{
  assert.equal(requireRealResult(result()).mode,'ocx');
  for(const patch of [{is_demo:true},{is_demo:undefined},{mode:'demo'},{lines:[]},{visions:[]},{visions:['']},{disclaimer:''}]){
    assert.throws(()=>requireRealResult({...result(),...patch}));
  }
  const duplicate=result();duplicate.lines[3]=duplicate.lines[0];
  assert.throws(()=>requireRealResult(duplicate));
  const incomplete=result();incomplete.lines[0].reading='';
  assert.throws(()=>requireRealResult(incomplete));
});

test('failure screen does not mistake request errors for poor lighting',async()=>{
  const views=await readFile(new URL('../src/palm_frontend/views.js',import.meta.url),'utf8');
  assert.match(views,/id: 'failureTitle'\}, '요청을 완료하지'/);
  assert.doesNotMatch(views,/다시 모아 주세요/);
  assert.match(views,/id: 'retry'.*text: '다시 시도'/);
});

test('visitor UI contains no operator setup or demonstration path',async()=>{
  const html=await readFile(new URL('../src/palm_backend/web/index.html',import.meta.url),'utf8');
  const source=await readFile(new URL('../src/palm_frontend/app.js',import.meta.url),'utf8');
  const views=await readFile(new URL('../src/palm_frontend/views.js',import.meta.url),'utf8');
  assert.doesNotMatch(`${html}\n${views}`,/id="(?:operator|settings|loginForm|configForm|resultMode|mode|disclaimer)"/);
  assert.doesNotMatch(`${source}\n${views}`,/시연|demoWithoutPhoto|operatorKey|\/v1\/config|\/v1\/operator/);
  assert.match(views,/id: 'consent'/);
  assert.match(views,/id: 'about'/);
  assert.match(source,/requireRealResult\(view\.result\)/);
  assert.match(html,/id="app"/);
  assert.match(html,/src="\/app\.js" type="module"/);
});
