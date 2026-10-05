const test=require('node:test'),assert=require('node:assert/strict');
const b=require('../web/dsb-backfill.js');
const {createSaver}=require('../web/dsb-save.js');
const ctx={month:'2026-10',today:'2026-10-05'};
const example='今日大新港元結餘 100000\n5號轉走5000\n3號收到20000\n其餘日子冇交易';
const reconstruct=(text,options={})=>b.reconstruct(b.parse(text,ctx),{start:'2026-10-01',today:ctx.today,...options});
test('spoken deposits and withdrawals reconstruct all days in cents; today remains provisional',()=>{
  const r=reconstruct(example);
  assert.deepEqual(r.rows.map(row=>row.amount),[85000,85000,105000,105000,100000]);
  assert.deepEqual(r.rows.map(row=>row.provisional),[false,false,false,false,true]);
  assert.equal(r.ready,true);
});
test('missing dates make previous balances unknown until completeness is explicitly confirmed',()=>{
  const r=reconstruct(example.replace('\n其餘日子冇交易',''));
  assert.deepEqual(r.missing,['2026-10-02','2026-10-04']);
  assert.deepEqual(r.rows.map(row=>row.amount),[null,null,null,105000,100000]);
  assert.equal(r.ready,false);
  assert.equal(reconstruct(example.replace('\n其餘日子冇交易',''),{complete:true}).rows[0].amount,85000);
});
test('dates, English directions, punctuation, decimals and compound numeric units',()=>{
  for(const text of ['今日結餘1,000,000.50\n10/3 CR 2萬5千','今日結餘1,000,000.50\n3/10 +25000','今日結餘1,000,000.50；10月3日存入25k']){
    const p=b.parse(text,ctx);assert.deepEqual(p.issues,[]);assert.equal(p.transactions[0].cents,2500000);assert.equal(p.anchor.cents,100000050);
  }
  const p=b.parse('今日結餘100000，3號收到20000，轉走5000，其餘日子冇交易',ctx);
  assert.deepEqual(p.issues,[]);assert.equal(p.transactions.length,2);assert.equal(p.remainderConfirmed,true);
  assert.equal(b.cents('2.5萬'),2500000);assert.equal(b.cents('0.29'),29);
});
test('ambiguous, pending, foreign currency, inconsistent and extra numeric data never get guessed',()=>{
  for(const line of ['3號 5000','3號存入-5000','3號支出+5000','3號存入1,2','3號存入2.001','3號 USD存入20','3號待入帳存入20','3號未收到20','3號存入5000 戶口123456','32號存入20','6號存入20']){
    assert.ok(b.parse('今日結餘100000\n'+line,ctx).issues.length,line);
  }
  assert.ok(b.parse('今日結餘100000\n今日結餘200000',ctx).issues.length);
  assert.match(b.parse('今日結餘100000\n3號5000',ctx).issues[0].message,/存入定支出/);
  assert.ok(b.parse('今日結餘100000\n<script>alert(1)</script>',ctx).issues.length);
});
test('same-day same-amount transactions require confirmation and are never silently deduplicated',()=>{
  const text=example+'\n3號收到20000';
  assert.throws(()=>reconstruct(text),/同額/);
  assert.equal(reconstruct(text,{allowDuplicates:true}).rows[0].amount,65000);
});
test('existing conflicts are disclosed, same amounts and today snapshot cause no conflict',()=>{
  const r=reconstruct(example,{existing:{'2026-10-01':85000,'2026-10-02':99999,'2026-10-05':50}});
  assert.deepEqual(r.conflicts,['2026-10-02']);
});
test('cross-month start can reconstruct the nonholiday balance needed at month start',()=>{
  const r=reconstruct(example+'\n1號存入10000',{start:'2026-09-30'});
  assert.equal(r.rows[0].amount,75000);assert.equal(r.rows[0].date,'2026-09-30');
  assert.throws(()=>reconstruct(example+'\n1號存入10000'),/起點/);
});
test('negative reverse balance and transaction/no-transaction contradictions are rejected',()=>{
  assert.throws(()=>reconstruct('今日結餘10\n3號存入20\n其餘日子冇交易'),/負數/);
  assert.throws(()=>reconstruct(example+'\n3號冇交易'),/同時/);
  assert.throws(()=>reconstruct(example+'\n3號轉走20000\n3號冇交易'),/同時/);
});
test('excessive payload fails locally with zero network calls',async()=>{
  let calls=0;
  const save=createSaver({storage:{getItem:()=>null,setItem(){},removeItem(){}},makeId:()=> 'request-12345',send:async()=>{calls++;}});
  await assert.rejects(save({large:'中'.repeat(4000)}),/大小上限/);assert.equal(calls,0);
});
