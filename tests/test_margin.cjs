const test=require('node:test');
const assert=require('node:assert/strict');
const {calculateMargin}=require('../web/margin.js');
const hkd={currency:'HKD',tiers:[
  {lower:0,upper:780000,rate:6.631,notes:[]},
  {lower:780000,upper:7800000,rate:6.131,notes:[]},
  {lower:7800000,upper:780000000,rate:5.631,notes:[]},
  {lower:780000000,upper:null,rate:5.631,notes:[2]}
]};
const usd={currency:'USD',tiers:[
  {lower:0,upper:100000,rate:5.38,notes:[]},
  {lower:100000,upper:1000000,rate:4.88,notes:[]},
  {lower:1000000,upper:50000000,rate:4.63,notes:[]},
  {lower:50000000,upper:null,rate:4.38,notes:[1]}
]};
test('HKD million splits at 780k; a tier rate cannot apply to the full balance',()=>{
  const result=calculateMargin(hkd,1000000);
  assert.ok(Math.abs(result.rate-6.521)<1e-10);
  assert.deepEqual(result.segments,[{amount:780000,rate:6.631},{amount:220000,rate:6.131}]);
  assert.ok(Math.abs(result.dailyInterest-65210/365)<1e-10);
});
test('USD million splits at 100k; uses 360 day interest basis',()=>{
  const result=calculateMargin(usd,1000000);
  assert.ok(Math.abs(result.rate-4.93)<1e-10);
  assert.ok(Math.abs(result.dailyInterest-49300/360)<1e-10);
  assert.equal(result.dayBasis,360);
});
test('boundaries remain in lower tier without special large-loan terms',()=>{
  assert.equal(calculateMargin(hkd,780000).rate,6.631);
  assert.equal(calculateMargin(usd,100000).rate,5.38);
  assert.doesNotThrow(()=>calculateMargin(usd,50000000));
  assert.throws(()=>calculateMargin(usd,50000000.01),/附加費/);
  assert.throws(()=>calculateMargin(hkd,780000001),/個別條款/);
});
test('invalid amount and missing coverage fail rather than fabricate an estimate',()=>{
  for(const amount of [0,-1,NaN,Infinity])assert.throws(()=>calculateMargin(hkd,amount),/有效借款金額/);
  assert.throws(()=>calculateMargin({...hkd,tiers:[hkd.tiers[0]]},1000000),/未涵蓋/);
  assert.throws(()=>calculateMargin({...hkd,tiers:[hkd.tiers[0],hkd.tiers[2]]},1000000),/不完整/);
});
