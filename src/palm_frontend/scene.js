import * as THREE from 'three';
import {gsap} from 'gsap';

const canvas = document.getElementById('space');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, .1, 80);
const world = new THREE.Group();
scene.add(world);
const state = {journey:0, drift:0, blossoms:0};
let renderer, frame, transition, transitionTimer, finishTransition, lost=false, stage='welcome', motif='life', last=0;
let seed=719;
const layers=[];
function random(){seed=seed*16807%2147483647;return(seed-1)/2147483646;}
function paper(ctx,w,h){
  ctx.save();
  for(let i=0;i<10000;i++){
    const x=random()*w,y=random()*h;
    ctx.fillStyle=i%2?'rgba(18,28,31,.07)':'rgba(249,232,193,.06)';
    ctx.fillRect(x,y,.5+random()*2,.5+random()*2);
  }
  ctx.restore();
}
function texture(w,h,draw){
  const c=document.createElement('canvas');c.width=w;c.height=h;
  const ctx=c.getContext('2d');draw(ctx,w,h);paper(ctx,w,h);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=2;return t;
}
function plane(tex,w,h,x,y,z,speed=0){
  const mesh=new THREE.Mesh(new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false}));
  mesh.position.set(x,y,z);world.add(mesh);layers.push({mesh,x,y,speed});return mesh;
}
const sky=texture(1024,768,(c,w,h)=>{
  const g=c.createLinearGradient(0,0,0,h);g.addColorStop(0,'#513b42');g.addColorStop(.52,'#82534b');g.addColorStop(1,'#bd8664');c.fillStyle=g;c.fillRect(0,0,w,h);
  c.strokeStyle='#e3bd8914';for(let i=0;i<100;i++){c.beginPath();c.moveTo(i*13,0);c.lineTo(i*13-120,h);c.stroke();}
});
plane(sky,36,24,0,1,-18);
const moon=texture(384,384,(c)=>{
  c.fillStyle='#e4ceb0';c.beginPath();c.arc(192,192,170,0,Math.PI*2);c.fill();
  c.strokeStyle='#71655250';c.lineWidth=1;for(let i=0;i<5;i++){c.beginPath();c.arc(192,192,157-i*5,0,Math.PI*2);c.stroke();}
});
plane(moon,3,3,4.5,3.1,-12,.02);
function mountains(color,offset){return texture(1400,700,(c,w,h)=>{
  const peaks=[];for(let i=0;i<=18;i++)peaks.push([i*w/18,120+random()*270+offset]);
  c.beginPath();c.moveTo(-20,h);c.lineTo(-20,420);for(const [x,y]of peaks)c.lineTo(x,y);c.lineTo(w+20,h);c.closePath();c.fillStyle=color;c.fill();c.strokeStyle='#203536';c.lineWidth=2;c.stroke();
  c.save();c.clip();
  for(let n=0;n<65;n++){
    c.beginPath();c.moveTo(-30,h);for(const [x,y]of peaks)c.lineTo(x-70+n*7,y+25+n*9);c.lineTo(w+100,h);c.strokeStyle=n%4?'#243d3c50':'#e1c39350';c.lineWidth=1;c.stroke();
  }
  c.restore();
});}
plane(mountains('#78877e',-50),29,14,0,-.7,-11,.025);
plane(mountains('#446c6a',30),27,12,-1,-2.3,-8,.04);
plane(mountains('#244c54',65),25,10,0,-3.7,-5,.06);
const cloudTexture=texture(1024,320,(c)=>{
  c.fillStyle='#bfc3ad';c.strokeStyle='#334e4b';c.lineWidth=2;
  c.beginPath();c.moveTo(0,240);c.bezierCurveTo(40,200,80,245,110,190);c.bezierCurveTo(80,100,210,75,260,130);c.bezierCurveTo(300,20,450,30,465,115);c.bezierCurveTo(550,60,610,90,620,155);c.bezierCurveTo(700,105,780,140,770,185);c.bezierCurveTo(900,160,980,210,1024,240);c.bezierCurveTo(780,305,260,285,0,240);c.fill();c.stroke();
  for(let i=0;i<5;i++){c.beginPath();c.moveTo(70+i*30,235+i*4);c.bezierCurveTo(330,190+i*5,700,260+i*4,900-i*22,235+i*4);c.strokeStyle='#526b5b70';c.stroke();}
});
plane(cloudTexture,11,3.2,-5,3.8,-6,.12);
plane(cloudTexture,8,2.5,6,1.8,-3,-.09);
plane(cloudTexture,10,3,-7,-.3,-2,.08);
function waves(color){return texture(1600,500,(c,w,h)=>{
  for(let row=0;row<4;row++){
    const y=100+row*125;
    for(let col=-1;col<12;col++){
      const x=col*160+(row%2)*80;
      c.beginPath();c.arc(x,y,145,Math.PI,0);c.lineTo(x+145,h);c.lineTo(x-145,h);c.closePath();c.fillStyle=color;c.fill();
      for(let r=145;r>25;r-=10){c.beginPath();c.arc(x,y,r,Math.PI,0);c.strokeStyle=r%20===5?'#172f37':'#d2c29644';c.lineWidth=1.8;c.stroke();}
    }
  }
});}
plane(waves('#3e686a'),28,6.5,0,-5.7,-3,.075);
const boatTex=texture(400,200,(c)=>{
  const paths=[[[25,60],[180,110],[350,45],[260,150],[145,175]],[[110,130],[170,18],[210,105]],[[170,18],[285,90],[210,105]]];
  for(const [i,p] of paths.entries()){c.beginPath();p.forEach(([x,y],j)=>j?c.lineTo(x,y):c.moveTo(x,y));c.closePath();c.fillStyle=['#e7dbbd','#f1e4c8','#a6b7aa'][i];c.fill();c.strokeStyle='#243d43';c.lineWidth=3;c.stroke();}
});
const boat=plane(boatTex,1.8,.9,3,-2.5,-.5,.1);
plane(waves('#487c78'),26,6.5,0,-6.5,0,-.09);
plane(waves('#315d61'),27,6,0,-7.5,1,.13);
const flowerTexture=texture(128,128,(c)=>{
  c.fillStyle='#d3a38e';c.strokeStyle='#564b48';c.lineWidth=1.5;
  for(let i=0;i<5;i++){c.save();c.translate(64,64);c.rotate(i*Math.PI*2/5);c.beginPath();c.ellipse(0,-23,13,25,0,0,Math.PI*2);c.fill();c.stroke();c.restore();}
  c.fillStyle='#e6cf93';c.beginPath();c.arc(64,64,8,0,Math.PI*2);c.fill();
});
const flowers=[];
for(let i=0;i<9;i++){
  const mesh=plane(flowerTexture,.22+i%3*.1,.22+i%3*.1,1+i*.6,-1+i%3*.6,1.5,.015);
  mesh.material.opacity=0;flowers.push(mesh);
}
const butterfly=new THREE.Group();butterfly.position.set(3,1,2);world.add(butterfly);
const wingTex=texture(256,384,(c)=>{
  c.beginPath();c.moveTo(12,200);c.bezierCurveTo(20,20,230,-15,225,100);c.bezierCurveTo(250,180,180,205,145,215);c.bezierCurveTo(245,270,190,380,110,340);c.bezierCurveTo(60,320,20,260,12,200);c.fillStyle='#dbc08a';c.fill();c.strokeStyle='#293f40';c.lineWidth=4;c.stroke();
  for(let i=0;i<8;i++){c.beginPath();c.moveTo(15,200);c.quadraticCurveTo(90,180-i*18,200-i*9,55+i*20);c.strokeStyle='#86664b';c.lineWidth=2;c.stroke();}
  c.beginPath();c.ellipse(137,114,27,42,-.5,0,Math.PI*2);c.strokeStyle='#38575b';c.lineWidth=8;c.stroke();
});
const wings=[];
for(const sign of [-1,1]){
  const hinge=new THREE.Group();const wing=new THREE.Mesh(new THREE.PlaneGeometry(.7,1),new THREE.MeshBasicMaterial({map:wingTex,transparent:true,side:THREE.DoubleSide,depthWrite:false}));
  wing.position.x=sign*.32;wing.scale.x=sign;hinge.add(wing);butterfly.add(hinge);wings.push({hinge,sign});
}
function resize(){
  if(!renderer)return;
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setSize(innerWidth,innerHeight,false);
  camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();
}
function render(now=0){
  if(!renderer||lost||document.hidden)return;
  const t=motion.matches?0:now*.001;
  camera.position.set(Math.sin(state.journey*Math.PI)*.4+state.drift*.28,state.journey*.35,12-state.journey*4);camera.lookAt(0,0,-3);
  const mobile=innerWidth<700;
  world.position.x=mobile?-1.8:0;
  for(const l of layers){l.mesh.position.x=l.x+Math.sin(t*.12+l.mesh.position.z)*l.speed*5+state.drift*l.speed*2;l.mesh.position.y=l.y+Math.sin(t*.3+l.x)*l.speed*.22;}
  flowers.forEach((flower,i)=>{flower.material.opacity=state.blossoms;flower.rotation.z=t*.15+i;flower.position.y=-1+(i%3)*.6+Math.sin(t*.5+i)*.22;});
  boat.rotation.z=Math.sin(t*.65)*.045;boat.position.y=-2.5+Math.sin(t*.8)*.08;
  butterfly.position.set((mobile?1.8:3)+Math.sin(t*.32)*1.1+state.journey*1.8,1.1+Math.cos(t*.43)*.45+state.journey*.8,2+state.journey*2);
  butterfly.rotation.z=Math.sin(t*.4)*.15;
  for(const {hinge,sign}of wings)hinge.rotation.y=sign*(.35+Math.sin(t*3)*.7);
  renderer.render(scene,camera);last=now;
}
function loop(now){if(document.hidden||lost)return;if(now-last>33)render(now);if(!motion.matches||transition)frame=requestAnimationFrame(loop);}
function resume(){cancelAnimationFrame(frame);render(performance.now());if(!document.hidden&&!lost&&(!motion.matches||transition))frame=requestAnimationFrame(loop);}
function cancelTransition(){clearTimeout(transitionTimer);transition?.kill();transition=null;if(finishTransition){const done=finishTransition;finishTransition=null;done(false);}state.journey=0;}
function setStage(next){cancelTransition();stage=next;resume();}
function transit(){
  cancelTransition();if(motion.matches||!renderer||lost||document.hidden)return Promise.resolve(true);
  return new Promise(resolve=>{
    finishTransition=resolve;
    const complete=()=>{clearTimeout(transitionTimer);transition?.kill();transition=null;finishTransition=null;resolve(true);};
    transitionTimer=setTimeout(complete,3200);
    transition=gsap.timeline({onComplete:complete}).to(state,{journey:1,duration:2.2,ease:'power2.inOut'});
    resume();
  });
}
function setMotif(name){
  motif=name;gsap.killTweensOf(state,'drift,blossoms');
  const value={life:0,heart:2,head:-2,fate:4,past:5,future:4}[name]||0;
  const blossoms=name==='heart'?1:0;
  if(motion.matches){state.drift=value;state.blossoms=blossoms;render();}else gsap.to(state,{drift:value,blossoms,duration:2,ease:'sine.inOut'});
  document.body.dataset.landscape=name;resume();
}
try{
  renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:'low-power'});
  renderer.setClearColor('#283e43',0);resize();resume();
}catch{document.body.classList.add('fallback-scene');}
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true;cancelTransition();cancelAnimationFrame(frame);document.body.classList.add('fallback-scene');});
canvas.addEventListener('webglcontextrestored',()=>{lost=false;document.body.classList.remove('fallback-scene');resize();resume();});
addEventListener('resize',()=>{resize();resume();});addEventListener('visibilitychange',resume);motion.addEventListener('change',resume);
addEventListener('pagehide',()=>{cancelTransition();cancelAnimationFrame(frame);});
window.PalmScene={setStage,transit,cancelTransition,chapter:setMotif,line:setMotif,get status(){return{stage,motif,webgl:!!renderer&&!lost,reducedMotion:motion.matches,layerCount:layers.length,journey:state.journey};}};
