// Local-only synthetic layout fixture. No real photo, API request or detected result.
import {renderApp} from '../src/palm_frontend/views.js';
const root=document.getElementById('app');
const names=['life','heart','head','fate'];
const paths={life:[{x:.37,y:.4},{x:.24,y:.52},{x:.28,y:.7},{x:.4,y:.83}],heart:[{x:.25,y:.36},{x:.47,y:.43},{x:.72,y:.35}],head:[{x:.3,y:.49},{x:.5,y:.54},{x:.73,y:.6}],fate:[]};
const svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 760"><rect width="600" height="760" fill="#1a1a19"/><text x="25" y="40" fill="white" font-size="20">SYNTHETIC LAYOUT TEST</text><path d="M170 660L145 470 80 360Q60 310 100 300L170 370 155 155Q150 110 180 110Q210 110 215 160L230 290 230 100Q230 65 260 65Q285 65 285 105L295 280 310 110Q315 75 345 90Q365 100 360 135L355 300 380 175Q390 140 415 150Q435 165 420 205L410 475Q400 590 350 660Z" fill="#bfb2a0"/><path d="M222 304Q140 400 168 532L240 630M150 274Q282 327 432 266M180 372Q300 410 438 456" fill="none" stroke="#65594d" stroke-width="3"/></svg>';
const state={screen:'reading',chapter:'present',lineIndex:0,visionIndex:0,sound:false,photo:{url:'data:image/svg+xml,'+encodeURIComponent(svg)},result:{hand:'unknown',lines:names.map(name=>({name,visibility:name==='fate'?'not_visible':'visible',trace:paths[name],trait:'합성 배치 테스트',description:'실제 손 사진이나 인식 결과가 아닙니다.',reading:'오버레이·선 선택의 배치 확인용 합성 데이터입니다.'})),visions:['합성 배치 테스트'],disclaimer:'실제 인식 결과가 아닙니다.'}};
const actions={line(index){state.lineIndex=index;draw();},chapter(chapter){state.chapter=chapter;draw();},vision(){},nextChapter(){},retake(){},finish(){},toggleSound(){},openAbout(){},mountCamera(){}};
function draw(){renderApp(root,state,actions);}
draw();
