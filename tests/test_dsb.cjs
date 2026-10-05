const test=require('node:test'),assert=require('node:assert/strict');
const m=require('../web/dsb-math.js');
const {createSaver}=require('../web/dsb-save.js');
const cal={years:[2024,2025,2026,2027],dates:['2026-10-01','2026-10-19','2026-04-03','2026-04-04','2026-04-06','2026-04-07','2026-02-17','2026-02-18','2026-02-19']};
const tiers=rate=>[{min:1,rate}];
const rule={cap:6000,day_basis:365,balance_basis:'previous_workday',minimum_balance:10000,
  base_tiers:[{min:10000,rate:.05},{min:500000,rate:.1}],thresholds:{fx:[10000]},vip_component_rate:.125,
  accounts:{vip:{debit:tiers(1.2),credit:tiers(.3),fx:tiers(.7),stock:tiers(1.2)}}};
const tasks={payroll:true,debit:10000,credit:3000,fx:10000,fund:false,stock:50000,vip1:true,vip2:true};
const settings={account:'vip',basic_rate:.001,costs:{debit:0,credit:0,fx:0,stock:0,other:0}};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
function input(month='2026-10',asOf='2026-10-03'){
  const balances={};for(const d of m.monthDates(month))balances[m.effectiveDate(d,cal)]=1000000;
  return {month,asOf,rule,settings,calendar:cal,balances,movements:[],currentBalance:1000000};
}
test('ordinary Saturday counts; Sunday and consecutive red days use preceding working day',()=>{
  assert.equal(m.effectiveDate('2026-10-03',cal),'2026-10-03');
  assert.equal(m.effectiveDate('2026-10-04',cal),'2026-10-03');
  assert.equal(m.effectiveDate('2026-10-19',cal),'2026-10-17');
  for(const d of ['03','04','05','06','07'])assert.equal(m.effectiveDate('2026-04-'+d,cal),'2026-04-02');
});
test('cross-month and cross-year anchors cannot silently become zero',()=>{
  const i=input('2026-10','2026-10-02');delete i.balances['2026-09-30'];
  assert.throws(()=>m.calculate(i,tasks),/2026-09-30/);
  assert.throws(()=>m.effectiveDate('2028-01-01',cal),/2028 年/);
  const jan={years:[2027],dates:['2027-01-01']};
  assert.throws(()=>m.effectiveDate('2027-01-01',jan),/2026 年/);
});
test('a Sunday withdrawal leaves Sunday interest unchanged and affects Monday',()=>{
  const i=input('2026-10','2026-10-04');i.movements=[{date:'2026-10-04',amount:-700000}];
  const result=m.calculate(i,tasks);
  assert.equal(result.rows[3].balance,1000000);assert.equal(result.rows[3].source,'2026-10-03');
  assert.equal(result.rows[4].balance,300000);close(result.rows[4].rate,3.45);
  // A recorded holiday balance is deliberately ignored for that day's interest.
  i.balances['2026-10-04']=3;assert.equal(m.calculate(i,tasks).rows[3].balance,1000000);
});
test('raw daily sum, 6000 cap, VIP and basic interest remain separate',()=>{
  const i=input();i.currentBalance=3000000;
  const r=m.calculate(i,tasks);close(r.uncappedCore,(2*1000000+29*3000000)*.035/365);
  assert.equal(r.core,6000);close(r.vip,(2*1000000+29*3000000)*.0025/365);
  close(r.gross,r.core+r.vip+r.basic);
  assert.equal(m.coreRate(rule,'vip',tasks,9999),0);
  close(m.coreRate(rule,'vip',tasks,10000),3.45);
  close(m.coreRate(rule,'vip',tasks,500000),3.5);
  assert.equal(m.coreRate(rule,'vip',{...tasks,payroll:false},1000000),0);
});
test('midmonth solver agrees with independent balance-days arithmetic to the cent',()=>{
  const i=input('2026-10','2026-10-16');i.movements=[{date:'2026-10-20',amount:-800000},{date:'2026-10-27',amount:300000}];
  const expected=(6000*365/.035-15*1000000+12*800000-5*300000)/16;
  const s=m.solve(i,tasks);assert.equal(s.opening,Math.ceil(expected*100)/100);
  assert.ok(s.result.uncappedCore>=6000);assert.ok(m.calculate({...i,currentBalance:s.opening-.01},tasks).uncappedCore<6000);
});
test('adjustment on Sunday plus Monday holiday has two more fixed interest days',()=>{
  const i=input('2026-10','2026-10-18'),s=m.solve(i,tasks);
  close(s.result.fixedCore,19*1000000*.035/365);
  const expected=(6000*365/.035-19*1000000)/12;
  assert.equal(s.opening,Math.ceil(expected*100)/100);
});
test('funding planner never promises unfundable planned withdrawals',()=>{
  const i=input();i.movements=[{date:'2026-10-04',amount:-5000000}];
  assert.throws(()=>m.calculate(i,tasks),/低於零/);
  assert.ok(m.solve(i,tasks).opening>=5000000);
});
test('month closed, cap already reached and missing tasks have explicit outcomes',()=>{
  const i=input('2026-10','2026-11-01');assert.equal(m.solve(i,tasks).status,'no_remaining_days');
  const j=input('2026-10','2026-10-31');Object.keys(j.balances).forEach(d=>j.balances[d]=3000000);
  assert.equal(m.solve(j,tasks).status,'cap_reached');assert.equal(m.solve(j,tasks).opening,0);
  assert.equal(m.solve(input(),{...tasks,payroll:false}).status,'unreachable');
});
test('leap year uses 29 days divided by 365; unknown costs never become zero',()=>{
  const i=input('2024-02','2024-03-01'),r=m.calculate(i,tasks);close(r.uncappedCore,29*1000000*.035/365);
  assert.equal(m.calculate({...i,settings:{...settings,basic_rate:null}},tasks).gross,null);
  assert.equal(m.calculate({...i,settings:{...settings,costs:{...settings.costs,fx:null}}},tasks).net,null);
});
test('eligible-from and historical rules are distinct and never stack overlapping promos',()=>{
  const i=input();i.settings={...settings,eligible_from:'2026-10-10'};
  close(m.calculate(i,tasks).core,22*1000000*.035/365);
  i.rule={...rule,legacy_core_rate:3,balance_basis:'entered'};i.asOf='2026-11-01';i.settings=settings;i.balances['2026-10-01']=1000000;
  for(const d of m.monthDates(i.month))i.balances[d]=1000000;
  i.balances['2026-10-04']=0;close(m.calculate(i,tasks).core,30*1000000*.03/365);
});
test('bulk data rejects malformed commas, duplicate dates, negatives and code',()=>{
  assert.deepEqual(m.parseLines('2026-10-02 1,234.56','2026-10'),[{date:'2026-10-02',amount:1234.56}]);
  for(const text of ['2026-10-02 1,2','2026-10-02 -2','2026-10-32 123','2026-10-02 =alert(1)','2026-10-02 10\n2026-10-02 20'])assert.throws(()=>m.parseLines(text,'2026-10'));
});
test('lost save response reuses one token and never mechanically retries',async()=>{
  const store=new Map(),payloads=[];let calls=0;
  const save=createSaver({storage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},makeId:()=>String(++calls),send:async(_url,options)=>{
    const payload=JSON.parse(options.body).payload;payloads.push(payload);if(payloads.length===1)throw new Error('lost reply');
    return {ok:true,json:async()=>({ok:true,committed:true,event_id:payload.event_id,dsb:{version:1,balances:{},months:{}}})};
  }});
  await assert.rejects(save({month:'2026-10'}),/lost reply/);assert.equal(payloads.length,1);
  await save({month:'2026-10'});assert.equal(calls,1);assert.deepEqual(payloads[0],payloads[1]);
});
