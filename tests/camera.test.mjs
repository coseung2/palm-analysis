import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {cameraErrorMessage, createCamera, sourceCrop} from '../src/palm_frontend/camera.js';

function fixture() {
  let stopped = 0, played = 0;
  const stream = {getTracks: () => [{stop() { stopped++; }}]};
  const video = {setAttribute() {}, srcObject: null, parentElement: null, async play() { played++; }};
  return {stream, video, get stopped() { return stopped; }, get played() { return played; }};
}
const named = name => Object.assign(new Error(name), {name});

test('mirrored preview is pinned to the full camera slot', async () => {
  const css = await readFile(new URL('../src/palm_backend/web/style.css', import.meta.url), 'utf8');
  assert.match(css, /#cameraSlot\{[^}]*inset:0;[^}]*overflow:hidden/);
  assert.match(css, /#cameraSlot video\{[^}]*display:block;inset:0;[^}]*transform:scaleX\(-1\)/);
});

test('webcam crop matches a centered guide with cover and mirroring', () => {
  const preview = {left: 100, top: 50, width: 400, height: 300};
  const guide = {left: 180, top: 80, width: 240, height: 240};
  assert.deepEqual(sourceCrop(640, 480, preview, guide), {x: 128, y: 48, width: 384, height: 384});
  const wide = sourceCrop(1920, 1080, preview, guide);
  assert.deepEqual(wide, {x: 528, y: 108, width: 864, height: 864});
});

test('off-center guide is unmirrored into the corresponding source region', () => {
  assert.deepEqual(sourceCrop(1000, 500, {left:0,top:0,width:500,height:250}, {left:50,top:25,width:100,height:100}), {x:700,y:50,width:200,height:200});
  assert.equal(sourceCrop(0, 500, {width:500,height:250}, {width:100,height:100}), null);
});

test('camera falls back to device defaults for rejected constraints', async () => {
  const f = fixture(), calls = [];
  const camera = createCamera({video: f.video, getUserMedia: async constraints => {
    calls.push(constraints);
    if (calls.length === 1) throw named('OverconstrainedError');
    return f.stream;
  }});
  assert.equal(await camera.open(), true);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1], {video: true, audio: false});
  assert.equal(f.video.srcObject, f.stream);
  camera.stop(); assert.equal(f.stopped, 1);
});

test('capture saves only guide pixels rather than the full webcam frame', async () => {
  const f = fixture();
  Object.assign(f.video, {videoWidth:640, videoHeight:480, getBoundingClientRect:() => ({left:100,top:50,width:400,height:300})});
  const drawn = [];
  const canvas = {getContext:() => ({drawImage:(...args) => drawn.push(args)}), toBlob:callback => callback(new Blob(['test-only'], {type:'image/jpeg'}))};
  const previous = globalThis.document;
  globalThis.document = {
    getElementById:() => ({hidden:false, getBoundingClientRect:() => ({left:180,top:80,width:240,height:240})}),
    createElement:() => canvas,
  };
  const camera = createCamera({video:f.video, getUserMedia:async () => f.stream});
  try {
    await camera.open();
    const file = await camera.capture();
    assert.equal(file.type, 'image/jpeg');
    assert.deepEqual(drawn[0].slice(1), [128,48,384,384,0,0,384,384]);
    assert.equal(canvas.width,384); assert.equal(canvas.height,384);
  } finally {
    camera.stop();
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  }
});

test('camera does not repeatedly request a denied permission', async () => {
  const f = fixture(); let calls = 0;
  const camera = createCamera({video: f.video, getUserMedia: async () => { calls++; throw named('NotAllowedError'); }});
  await assert.rejects(camera.open(), {name: 'NotAllowedError'});
  assert.equal(calls, 1);
  assert.equal(camera.active, false);
});

test('camera resumes preview when a UI redraw replaces its slot', async () => {
  const f = fixture();
  const camera = createCamera({video: f.video, getUserMedia: async () => f.stream});
  await camera.open();
  const slot = {replaceChildren(video) { video.parentElement = this; }};
  camera.mount(slot);
  assert.equal(f.played, 2);
  camera.mount(slot); assert.equal(f.played, 2);
  camera.stop();
});

test('a cancelled permission request stops late camera tracks', async () => {
  const f = fixture(); let resolve;
  const camera = createCamera({video: f.video, getUserMedia: () => new Promise(r => { resolve = r; })});
  const pending = camera.open(); camera.stop(); resolve(f.stream);
  assert.equal(await pending, false);
  assert.equal(f.stopped, 1); assert.equal(camera.active, false);
});

test('failed playback releases the stream and reports distinct causes', async () => {
  const f = fixture(); f.video.play = async () => { throw named('NotReadableError'); };
  const camera = createCamera({video: f.video, getUserMedia: async () => f.stream});
  await assert.rejects(camera.open(), {name: 'NotReadableError'});
  assert.equal(f.stopped, 1); assert.equal(camera.active, false);
  assert.match(cameraErrorMessage(named('NotAllowedError')), /사이트 설정/);
  assert.match(cameraErrorMessage(named('NotReadableError')), /다른 앱/);
  assert.match(cameraErrorMessage(named('NotFoundError')), /카메라를 찾지/);
  assert.match(cameraErrorMessage(new Error('camera_unavailable')), /HTTPS/);
});
