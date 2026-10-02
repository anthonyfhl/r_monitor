const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createSaver}=require('../web/registration-save.js');
function storage(){const state=new Map();return {getItem:k=>state.get(k)||null,setItem:(k,v)=>state.set(k,v),removeItem:k=>state.delete(k)};}
const fields={promo_id:'2026-09',member:'Mum',status:'registered',registered_on:null};
function reply(id){return {ok:true,json:async()=>({ok:true,committed:true,event_id:id,registrations:{members:['Mum'],registrations:{},version:1}})};}

test('an accepted inbox message alone is never a saved record',async()=>{
  const s=storage();
  const save=createSaver({storage:s,makeId:()=> 'request-12345',send:async()=>({ok:true,json:async()=>({ok:true})})});
  await assert.rejects(save(fields),/未能確認/);
  assert.ok(s.getItem('esaver-unconfirmed-save'));
});
test('lost reply and tab reload reuse one token, without automatic POST retries',async()=>{
  const s=storage(),payloads=[];
  const first=createSaver({storage:s,makeId:()=> 'request-12345',send:async(_,options)=>{payloads.push(JSON.parse(options.body).payload);throw new Error('connection lost');}});
  await assert.rejects(first(fields));
  assert.equal(payloads.length,1);
  const next=createSaver({storage:s,makeId:()=>{throw new Error('must reuse token');},send:async(_,options)=>{const p=JSON.parse(options.body).payload;payloads.push(p);return reply(p.event_id);}});
  assert.equal((await next(fields)).version,1);
  assert.deepEqual(payloads[0],payloads[1]);
  assert.equal(s.getItem('esaver-unconfirmed-save'),null);
});
test('wrong request acknowledgement cannot display saved',async()=>{
  const save=createSaver({storage:storage(),makeId:()=> 'request-12345',send:async()=>reply('another-request')});
  await assert.rejects(save(fields),/未能確認/);
});
