(function(root){
  'use strict';
  const DAY=86400000;
  function iso(value){
    if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||!Number.isFinite(Date.parse(value))||new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)throw new Error('日期格式無效。');
    return value;
  }
  const shift=(d,n)=>new Date(Date.parse(iso(d))+n*DAY).toISOString().slice(0,10);
  function monthDates(month){
    if(!/^\d{4}-\d{2}$/.test(month))throw new Error('月份格式無效。');
    const first=iso(month+'-01'), result=[];
    for(let d=first;d.startsWith(month);d=shift(d,1))result.push(d);
    return result;
  }
  function holiday(date,calendar){
    iso(date);
    if(!calendar?.years?.includes(Number(date.slice(0,4))))throw new Error(`${date.slice(0,4)} 年香港公眾假期未完整核對，停止倒算。`);
    return new Date(date+'T00:00:00Z').getUTCDay()===0||calendar.dates.includes(date);
  }
  function effectiveDate(date,calendar){
    let value=date;
    for(let n=0;n<15;n++,value=shift(value,-1))if(!holiday(value,calendar))return value;
    throw new Error('連續紅日超出可核對範圍。');
  }
  function number(value,label,{negative=false}={}){
    if(typeof value!=='number'||!Number.isFinite(value)||(!negative&&value<0)||Math.abs(value)>1e11)throw new Error(`${label}須為有效${negative?'':'非負'}數字。`);
    return value;
  }
  function tierRate(tiers,amount){return [...tiers].reverse().find(t=>amount>=t.min)?.rate||0;}
  function coreRate(rule,account,tasks,balance){
    if(rule.legacy_core_rate!==undefined)return balance>0?rule.legacy_core_rate:0;
    if(!rule.accounts?.[account])throw new Error('所選期別未有完整戶口利率。');
    if(!tasks.payroll||balance<rule.minimum_balance)return 0;
    return tierRate(rule.base_tiers,balance)+['debit','credit','fx','stock'].reduce((sum,key)=>{
      const value=key==='fx'&&tasks.fund?rule.thresholds.fx[0]:Number(tasks[key]||0);
      return sum+tierRate(rule.accounts[account][key],value);
    },0);
  }
  function daily(rule,settings,tasks,balance,date){
    const eligible=(!rule.reward_start||date>=rule.reward_start)&&(!rule.reward_end||date<=rule.reward_end)&&(!settings.eligible_from||date>=settings.eligible_from);
    const rate=eligible?coreRate(rule,settings.account,tasks,balance):0;
    const vipRate=rule.legacy_vip_rate??(settings.account==='vip'?rule.vip_component_rate*((tasks.vip1?1:0)+(tasks.vip2?1:0)):0);
    const basicRate=settings.basic_rate??rule.legacy_basic_rate;
    return {rate,core:balance*rate/100/rule.day_basis,
      vip:Number.isFinite(vipRate)?balance*vipRate/100/rule.day_basis:null,
      basic:Number.isFinite(basicRate)?balance*basicRate/100/rule.day_basis:null};
  }
  function prepare(input){
    const {month,asOf,rule,settings,balances,calendar}=input, dates=monthDates(month);
    iso(asOf);
    if(asOf<dates[0]||asOf>shift(dates.at(-1),1))throw new Error('調整日期須在本月或下月首日。');
    if(!rule||!Number.isFinite(rule.cap)||rule.cap<=0||rule.day_basis!==365)throw new Error('本期計息條款未齊。');
    if(settings.basic_rate!==undefined&&settings.basic_rate!==null)number(settings.basic_rate,'基本年利率');
    for(const value of Object.values(settings.costs||{}))if(value!==null)number(value,'交易成本');
    if(settings.eligible_from)iso(settings.eligible_from);
    if(rule.reward_start&&rule.reward_start>dates.at(-1)||rule.reward_end&&rule.reward_end<dates[0])throw new Error('所選推廣不涵蓋本月。');
    const sourceDate=d=>rule.balance_basis==='entered'?d:effectiveDate(d,calendar);
    const mapped=dates.map(date=>({date,source:sourceDate(date)}));
    const required=[...new Set(mapped.filter(r=>r.source<asOf).map(r=>r.source))];
    const missing=required.filter(d=>balances[d]===undefined||balances[d]===null);
    if(missing.length){const error=new Error(`欠缺計息結餘：${missing.join('、')}。填妥後才可倒算。`);error.missing=missing;throw error;}
    required.forEach(d=>number(balances[d],d+' 結餘'));
    const movements=(input.movements||[]).map(m=>({date:iso(m.date),amount:number(m.amount,'預計變動',{negative:true})})).sort((a,b)=>a.date.localeCompare(b.date));
    if(movements.some(m=>m.date<asOf||m.date>dates.at(-1)))throw new Error('預計資金變動須在調整日起至月底之內。');
    const offsets={};let cumulative=0,minimum=0;
    for(const date of dates.filter(d=>d>=asOf)){
      cumulative+=movements.filter(m=>m.date===date).reduce((s,m)=>s+m.amount,0);
      offsets[date]=cumulative;minimum=Math.min(minimum,cumulative);
    }
    return {dates,mapped,offsets,minimum,rule,settings,balances,asOf};
  }
  function evaluate(context,tasks,opening){
    const {mapped,rule,settings,balances,asOf,offsets}=context;
    let core=0,vip=0,basic=0,balanceDays=0,pastCore=0,fixedCore=0;
    const rows=mapped.map(({date,source})=>{
      const projected=source>=asOf;
      const balance=projected?opening+offsets[source]:balances[source];
      if(balance<0)throw new Error('預計提款後結餘會低於零；請增加起始結餘或調整計劃。');
      const interest=daily(rule,settings,tasks,balance,date);
      core+=interest.core;vip=vip===null||interest.vip===null?null:vip+interest.vip;basic=basic===null||interest.basic===null?null:basic+interest.basic;
      balanceDays+=balance;
      if(date<asOf)pastCore+=interest.core;
      if(source<asOf)fixedCore+=interest.core;
      return {date,source,balance,projected,...interest};
    });
    const capped=Math.min(core,rule.cap),gross=vip===null||basic===null?null:capped+vip+basic;
    const costs=settings.costs, cost=costs&&['debit','credit','fx','stock','other'].every(k=>Number.isFinite(costs[k]))?Object.values(costs).reduce((a,b)=>a+b,0):null;
    return {rows,uncappedCore:core,core:capped,vip,basic,gross,pastCore,fixedCore,remaining:Math.max(0,rule.cap-pastCore),
      unused:Math.max(0,rule.cap-core),overCap:Math.max(0,core-rule.cap),cost,net:gross===null||cost===null?null:gross-cost,
      balanceDays,annualized:gross===null||!balanceDays?null:gross/balanceDays*rule.day_basis*100,
      netAnnualized:gross===null||cost===null||!balanceDays?null:(gross-cost)/balanceDays*rule.day_basis*100};
  }
  function calculate(input,tasks){
    const ctx=prepare(input),future=ctx.mapped.some(r=>r.source>=input.asOf);
    const opening=future?number(input.currentBalance,'調整前結餘'):0;
    return evaluate(ctx,tasks,opening);
  }
  function solve(input,tasks){
    const ctx=prepare(input),floor=Math.max(0,-ctx.minimum),future=ctx.mapped.some(r=>r.source>=input.asOf);
    const current=future?number(input.currentBalance,'調整前結餘'):0;
    // A planned withdrawal must remain fundable even if today's balance is too small.
    const atFloor=evaluate(ctx,tasks,floor);
    if(!future)return {status:atFloor.core>=ctx.rule.cap?'cap_reached':'no_remaining_days',opening:null,adjustment:null,result:atFloor};
    if(atFloor.uncappedCore>=ctx.rule.cap)return {status:atFloor.fixedCore>=ctx.rule.cap?'cap_reached':'target',opening:floor,adjustment:floor-current,result:atFloor};
    let low=floor,high=Math.max(1e6,floor+1);
    while(high<=1e11&&evaluate(ctx,tasks,high).uncappedCore<ctx.rule.cap)high*=2;
    if(high>1e11)return {status:'unreachable',opening:null,adjustment:null,result:atFloor};
    for(let n=0;n<70;n++){const mid=(low+high)/2;if(evaluate(ctx,tasks,mid).uncappedCore>=ctx.rule.cap)high=mid;else low=mid;}
    const target=Math.ceil(high*100)/100,result=evaluate(ctx,tasks,target);
    if(result.uncappedCore+1e-8<ctx.rule.cap)throw new Error('倒算驗證失敗，未能給出可靠目標。');
    return {status:'target',opening:target,adjustment:target-current,result};
  }
  function parseLines(text,month,{movement=false}={}){
    const found=new Set();
    return text.split(/\r?\n/).filter(l=>l.trim()).map((line,index)=>{
      const match=line.trim().match(/^(\d{4}-\d{2}-\d{2})[\s,]+([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)$/);
      if(!match)throw new Error(`第 ${index+1} 行請用「YYYY-MM-DD 金額」。`);
      const date=iso(match[1]);if(!date.startsWith(month))throw new Error(`第 ${index+1} 行不屬於所選月份。`);
      if(!movement&&found.has(date))throw new Error(`${date} 重複，請保留一筆結餘。`);found.add(date);
      const amount=number(Number(match[2].replaceAll(',','')),'金額',{negative:movement});
      return {date,amount};
    });
  }
  const api={iso,shift,monthDates,holiday,effectiveDate,coreRate,daily,calculate,solve,parseLines};
  if(typeof module!=='undefined')module.exports=api;else root.dsbMath=api;
})(globalThis);
