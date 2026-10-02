const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../web/http-guard.js'),'utf8');
function browser(fetch,store=new Map(),clock={now:1000000}){
  const context={window:{},navigator:{locks:{request:(_,action)=>action()}},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},fetch,Date:class extends Date{static now(){return clock.now;}},setTimeout:action=>action(),Math,JSON,Number,Error};
  vm.runInNewContext(code,context);return context.window.monitorHTTP;
}
function response(status,headers={}){return {status,ok:status===200,type:'basic',headers:{get:k=>headers[k]||null}};}
for(const status of [401,403,429])test(`HTTP ${status} stops this tab and another tab; repeat extends pause`,async()=>{
  let calls=0;const store=new Map(),clock={now:1000000};
  const fetch=async()=>{calls++;return response(status,{'Retry-After':'90000'});};
  const first=browser(fetch,store,clock),second=browser(fetch,store,clock);
  await assert.rejects(first.send('data.json'));
  const until=JSON.parse([...store.values()][0]).until;
  await assert.rejects(first.send('registrations.json'));await assert.rejects(second.send('inbox',{method:'POST'}));
  assert.equal(calls,1);assert.equal(first.canAutoLoad(),false);
  clock.now=until+1;await assert.rejects(second.send('data.json'));
  assert.ok(JSON.parse([...store.values()][0]).until-clock.now>until-1000000);
  assert.equal(calls,2);
});
test('server fault repairs GET once, never repeats a POST',async()=>{
  let calls=0;const guard=browser(async()=>{calls++;return response(503);});
  await guard.send('data.json');assert.equal(calls,2);
  await guard.send('inbox',{method:'POST'});assert.equal(calls,3);
});
test('bad request stops automatic reads without repeating request',async()=>{
  let calls=0;const guard=browser(async()=>{calls++;return response(404);});
  await guard.send('data.json');assert.equal(calls,1);assert.equal(guard.canAutoLoad(),false);
});
test('login HTML is a refusal, never repeatedly parsed as data',async()=>{
  let calls=0;const guard=browser(async()=>{calls++;return response(200,{'Content-Type':'text/html'});});
  await assert.rejects(guard.send('data.json'));await assert.rejects(guard.send('registrations.json'));
  assert.equal(calls,1);
});
