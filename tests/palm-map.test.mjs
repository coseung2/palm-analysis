import test from 'node:test';
import assert from 'node:assert/strict';
import {tracePoints, renderPalmMap} from '../src/palm_frontend/palm-map.js';

test('only visible bounded polylines are rendered, never a template', () => {
  const line={visibility:'visible',trace:[{x:.1,y:.2},{x:.8,y:.9}]};
  assert.deepEqual(tracePoints(line),[[100,200],[800,900]]);
  for(const bad of [{...line,visibility:'unclear'},{...line,trace:undefined},{...line,trace:[{x:-1,y:0},{x:1,y:1}]},{...line,trace:[{x:NaN,y:0},{x:1,y:1}]}]) assert.deepEqual(tracePoints(bad),[]);
});

test('map keeps original photo, selected line, SVG namespace and no invented traces', () => {
  const previous=globalThis.document;
  const create=(tag,ns=null)=>({tag,ns,children:[],attrs:{},setAttribute(k,v){this.attrs[k]=v;},append(...children){this.children.push(...children);}});
  globalThis.document={createElement:create,createElementNS:(ns,tag)=>create(tag,ns)};
  try {
    const result={lines:[{name:'life',visibility:'visible',trace:[{x:.1,y:.2},{x:.8,y:.9}]},{name:'heart',visibility:'unclear'}]};
    const map=renderPalmMap('blob:test-only',result,'life');
    const frame=map.children[0],svg=frame.children[1];
    assert.equal(frame.children[0].src,'blob:test-only');
    assert.equal(svg.ns,'http://www.w3.org/2000/svg');
    assert.equal(svg.attrs.preserveAspectRatio,'none');
    assert.equal(svg.children.length,1);
    assert.match(svg.children[0].attrs.class,/selected/);
    assert.match(map.children[1].textContent,/추정/);
    assert.equal(renderPalmMap(null,result,'life').children.length,1);
  } finally {
    if(previous===undefined) delete globalThis.document;else globalThis.document=previous;
  }
});
