import test from 'node:test';
import assert from 'node:assert/strict';
import {radarPoint, validScores} from '../src/palm_frontend/radar.js';

const five = ['상상력', '직관력', '논리력', '신중함', '집중력'].map((trait, i) => ({trait, score: 40 + i * 10, basis: 'x'}));

test('radar axes start at the top and scale scores to the radius', () => {
  assert.deepEqual(radarPoint(0, 5, 100, 100).map(Math.round), [0, -100]);
  assert.deepEqual(radarPoint(0, 5, 50, 100).map(Math.round), [0, -50]);
  assert.deepEqual(radarPoint(0, 5, 0, 100).map(v => Math.round(v) + 0), [0, 0]);
  assert.deepEqual(radarPoint(0, 5, 140, 100).map(Math.round), [0, -100]);
});

test('only visible lines with well-formed scores draw a radar', () => {
  assert.equal(validScores({visibility: 'visible', scores: five}).length, 5);
  assert.deepEqual(validScores({visibility: 'unclear', scores: five}), []);
  assert.deepEqual(validScores({visibility: 'visible'}), []);
  assert.deepEqual(validScores({visibility: 'visible', scores: [{...five[0], score: 120}, ...five.slice(1)]}), []);
  assert.deepEqual(validScores({visibility: 'visible', scores: [{...five[0], score: 4.5}, ...five.slice(1)]}), []);
});
