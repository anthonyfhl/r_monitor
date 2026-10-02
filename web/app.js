'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = (value, digits=3) => Number.isFinite(value) ? `${value.toFixed(digits)}%` : '—';
const shortDate = value => value ? value.slice(5).replace('-','/') : '—';
const colors = ['#c25e36','#287765','#8497aa','#b79454','#836e97','#55765c','#b97082','#527e91'];
let data, registrations, group='hkd', loanDays=90, hiddenSeries=new Set(), marginLinkOpened=false;

function navigate(){
  const page = location.hash === '#esaver' ? 'esaver' : 'rates';
  $('rates-page').hidden = page !== 'rates'; $('esaver-page').hidden = page !== 'esaver';
  document.querySelectorAll('[data-page]').forEach(el => el.classList.toggle('active',el.dataset.page===page));
  $('breadcrumb').textContent = page === 'esaver' ? 'eSaver 家庭紀錄' : '利率監察';
}
window.addEventListener('hashchange',navigate);

function plot(target, series, days=90){
  const now = data?.updated_at ? new Date(data.updated_at) : new Date();
  const cutoff = new Date(now); cutoff.setDate(cutoff.getDate()-days);
  const sets=series.map(s=>({...s,points:(s.points || []).filter(p=>new Date(p.date)>=cutoff && Number.isFinite(p.value))})).filter(s=>s.points.length);
  if(!sets.length){$(target).innerHTML='<div class="chart-empty">暫時未有已驗證嘅走勢資料</div>';return;}
  const all=sets.flatMap(s=>s.points), values=all.map(p=>p.value);
  let xmin=Math.min(...all.map(p=>new Date(p.date).getTime())), xmax=Math.max(...all.map(p=>new Date(p.date).getTime()));
  let ymin=Math.min(...values), ymax=Math.max(...values); const margin=Math.max((ymax-ymin)*.18,.15); ymin-=margin; ymax+=margin;
  if(xmin===xmax){xmin-=86400000*2; xmax+=86400000*2;}
  const x=t=>58+(new Date(t).getTime()-xmin)/(xmax-xmin)*878, y=v=>18+(ymax-v)/(ymax-ymin)*158;
  let svg=`<svg viewBox="0 0 980 220" role="img" aria-label="${esc(sets.map(s=>s.label).join('、'))} 年利率走勢"><title>${esc(sets.map(s=>s.label).join('、'))}，最近 ${days} 日</title>`;
  for(let i=0;i<5;i++){const v=ymin+(ymax-ymin)*i/4;svg+=`<line class="gridline" x1="58" x2="936" y1="${y(v)}" y2="${y(v)}"/><text x="44" y="${y(v)+4}" text-anchor="end" fill="#899489" font-size="12">${v.toFixed(2)}%</text>`;}
  for(let i=0;i<4;i++){const t=xmin+(xmax-xmin)*i/3;svg+=`<text x="${58+878*i/3}" y="207" text-anchor="${i===0?'start':i===3?'end':'middle'}" fill="#899489" font-size="12">${new Date(t).toISOString().slice(0,10)}</text>`;}
  sets.forEach((s,i)=>{
    const color=s.color||colors[i%colors.length];
    const d=s.points.map((p,j)=>`${j?'L':'M'}${x(p.date).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
    svg+=`<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round"/>`;
    const latest=s.points.at(-1); svg+=`<circle cx="${x(latest.date)}" cy="${y(latest.value)}" r="4" fill="${color}"><title>${esc(s.label)} ${latest.date}：${pct(latest.value,5)}</title></circle>`;
    if(s.points.length===1) svg+=`<text x="${Math.min(x(latest.date)+12,850)}" y="${y(latest.value)-12}" fill="${color}" font-size="12">${pct(latest.value,5)} · 開始記錄</text>`;
  });
  $(target).innerHTML=svg+'</svg>';
}

function renderLoans(){
  $('loans').innerHTML=data.loans.map((loan,i)=>{
    const current=loan.current, rate=current?.rate ?? loan.latest?.value;
    const previous=loan.points.length>1?loan.points.at(-2).value:null;
    const diff=current && previous!==null?rate-previous:null;
    let change=diff===null?'開始記錄':Math.abs(diff)<.000001?'息率不變':`${diff>0?'↑':'↓'} ${Math.abs(diff).toFixed(5)} 百分點`;
    return `<article class="loan-card" style="--card-color:${colors[i]}"><div class="loan-head"><div><p class="loan-label">${esc(loan.name)}</p><p class="loan-formula">${esc(loan.formula)}</p></div><span class="bank-tag">${i?'HASE':'HSBC'}</span></div><div class="loan-row"><div class="loan-number">${Number.isFinite(rate)?rate.toFixed(5):'—'}<span class="percent">${Number.isFinite(rate)?'%':''}</span></div><span class="${current?'small-pill':'badge warn'}">${current?change:'未取得今日基準'}</span></div><div class="loan-meta"><span>基準：${current?pct(current.base_rate,5):'未更新'}</span><span>基準日期 ${current?esc(current.source_date):esc(loan.latest?.date||'—')}</span></div>${i?'':'<p class="footnote" style="padding:12px 0 0;border:0">HIBOR 即香港銀行同業拆息；此貸款用 1 個月期。</p>'}</article>`;
  }).join('');
  const loans=data.loans.map(l=>l.current);
  if(loans.every(Boolean)){
    const diff=loans[0].rate-loans[1].rate;
    $('comparison').innerHTML=`<span>目前${diff>=0?'恒生 Asset Link':'滙豐滙財組合貸款'}息率較低 <strong>${Math.abs(diff).toFixed(5)} 百分點</strong></span><span>每借 100 萬港元，一年利息差約 <strong>HK$${(Math.abs(diff)*10000).toLocaleString('en',{maximumFractionDigits:0})}</strong></span>`;
  }else $('comparison').textContent='部分基準未更新，暫時無法比較今日貸款成本。';
  plot('loan-chart',data.loans.map((l,i)=>({label:l.name,points:l.points,color:colors[i]})),loanDays);
}

function renderMarkets(){
  const series=data.series.filter(s=>s.group===group);
  const active=series.filter(s=>!hiddenSeries.has(s.id));
  plot('market-chart',active.map(s=>({...s,color:colors[series.indexOf(s)%colors.length]})),loanDays);
  $('market-legend').innerHTML=series.map((s,i)=>`<button type="button" data-series="${s.id}" class="${hiddenSeries.has(s.id)?'off':''}" aria-pressed="${!hiddenSeries.has(s.id)}"><i style="background:${colors[i%colors.length]}"></i>${esc(s.label)}</button>`).join('');
  $('market-legend').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{hiddenSeries.has(b.dataset.series)?hiddenSeries.delete(b.dataset.series):hiddenSeries.add(b.dataset.series);renderMarkets();}));
  $('market-table').innerHTML=series.map(s=>{
    const latest=s.points.at(-1), old=s.points.at(-2); const diff=latest&&old?latest.value-old.value:null;
    const stale=latest&&(new Date()-new Date(latest.date))>7*86400000;
    const ok=s.ok===true&&!stale;
    return `<tr><td>${esc(s.label)}</td><td class="number rate-value">${pct(latest?.value, s.id.startsWith('hibor')?5:3)}</td><td class="number ${diff>0?'up':diff<0?'good':'flat'}">${diff===null?'—':`${diff>0?'+':''}${diff.toFixed(5)}`}</td><td>${esc(latest?.date||'—')}</td><td><span class="badge ${ok?'':'warn'}">${ok?'已驗證':s.ok===false?'本次未更新':stale?'資料較舊':'未驗證'}</span></td></tr>`;
  }).join('');
}

const currencyName={HKD:'港元',USD:'美元'};
const money=(value,ccy)=>`${ccy==='HKD'?'HK$':'US$'}${value.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const tierRange=t=>t.upper===null?`超過 ${t.lower.toLocaleString('en')}`:t.lower===0?`首 ${t.upper.toLocaleString('en')}`:`${t.lower.toLocaleString('en')}–${t.upper.toLocaleString('en')}`;
function marginCurrent(ccy){
  const item=data.ib_margin?.[ccy];
  return item?.tiers?.length&&data.health?.ib_rates?.ok===true&&item.date&&new Date()-new Date(item.date)<=36*3600000?item:null;
}
function renderMarginCalculator(){
  const ccy=$('margin-currency').value,item=marginCurrent(ccy);
  try{
    if(!item)throw new Error('本次未有已驗證嘅 IB 借款級別；取得新資料後先可以試算。');
    const result=marginMath.calculateMargin(item,Number($('margin-amount').value));
    $('margin-result').innerHTML=`<div class="margin-estimate"><div><p>加權平均年利率</p><strong>${pct(result.rate,5)}</strong></div><div><p>30 日利息估算</p><strong>${money(result.dailyInterest*30,ccy)}</strong></div></div><p class="margin-breakdown">${result.segments.map(s=>`${money(s.amount,ccy)} × ${pct(s.rate)}`).join(' ＋ ')}<br>每段按 ${result.dayBasis} 日計每日利息</p>`;
  }catch(error){$('margin-result').innerHTML=`<p class="margin-error" role="alert">⚠ ${esc(error.message)}</p>`;}
}
function renderMargin(){
  $('margin-cards').innerHTML=['HKD','USD'].map(ccy=>{
    const item=marginCurrent(ccy);
    if(!item)return `<article class="margin-card"><h3>${currencyName[ccy]} · ${ccy}</h3><p class="margin-error">本次未有完整、已驗證嘅借款利率。</p></article>`;
    return `<article class="margin-card"><div class="margin-card-heading"><h3>${currencyName[ccy]} · ${ccy}</h3><span class="badge">${esc(item.plan)}</span></div><div class="margin-headline"><strong>${pct(item.rate)}</strong><span>首 ${ccy} ${item.tiers[0].upper.toLocaleString('en')} 年利率</span></div><table class="margin-table"><thead><tr><th>分段借款額 · ${ccy}</th><th class="number">年利率</th></tr></thead><tbody>${item.tiers.map(t=>`<tr><td>${tierRange(t)}${t.notes.length?' <span class="margin-note-marker">*</span>':''}</td><td class="number">${pct(t.rate)}${t.notes.length?' *':''}</td></tr>`).join('')}</tbody></table>${item.tiers.some(t=>t.notes.length)?'<p class="margin-special">* 大額級別另有附加費或個別條款；公布利率未包含個別調整。</p>':''}<p class="margin-date">官方網頁核對日期 ${esc(item.date)}</p></article>`;
  }).join('');
  renderMarginCalculator();
}

function renderWarnings(){
  const failures=Object.entries(data.health||{}).filter(([key,value])=>value.ok===false);
  const messages=failures.map(([key,value])=>`${sourceName(key)}：${value.repair||value.error}`);
  messages.push(...(data.repair_events||[]));
  if(data.updated_at&&new Date()-new Date(data.updated_at)>36*3600000)messages.unshift('每日資料已超過 36 小時未更新；下方為最後有效紀錄。');
  if(!data.delivery_ok)messages.push('Telegram 未確認送達；變動紀錄已保留，通知尚未完成。');
  if(registrations?.sync_errors?.length)messages.push(...registrations.sync_errors);
  $('warnings').innerHTML=messages.length?`<details class="warning" open><summary>⚠ ${messages.length} 項資料或通知需要留意</summary>${messages.map(m=>`<p>${esc(m)}</p>`).join('')}</details>`:'';
}
function sourceName(key){return {hibor:'銀行同業拆息',prime_HSBC:'滙豐最優惠利率',prime_HASE:'恒生最優惠利率',prime_DBS:'星展最優惠利率',ib_rates:'盈透證券融資',fed_funds:'聯邦基金利率',sofr:'美元隔夜融資',treasury:'美國國債',fedwatch:'美國議息機率',hkd_forwards:'港元遠期匯價',esaver:'DBS eSaver'}[key]||key;}

function renderEsaver(){
  const offers=[...(data.promotions||[])].sort((a,b)=>b.reward_start.localeCompare(a.reward_start));
  const offer=offers[0];
  if(!offer){$('offer-summary').innerHTML='<div class="warning">未有已驗證嘅現有客戶推廣資料。</div>';return;}
  const closed=offer.registration_closed_early||!offer.reg_end||offer.reg_end<new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Hong_Kong'});
  const labels=[['hkd_200k','港元 20 萬'],['hkd_1m','港元 100 萬'],['hkd_5m','港元 500 萬'],['usd_25k','美元 2.5 萬']];
  $('offer-summary').innerHTML=`<section class="panel offer-panel"><div class="offer-header"><div><p class="eyebrow">LATEST EXISTING-CUSTOMER OFFER</p><h2>${esc(offer.promo_month)} 現有客戶推廣</h2></div><span class="badge ${closed?'warn':''}">${closed?'登記期已完':'接受登記'}</span></div><div class="offer-rates">${labels.map(([k,label])=>`<div class="offer-rate"><p>${label} · 合計年利率</p><strong>${pct(offer.rates[k])}</strong></div>`).join('')}</div><div class="offer-meta"><div><p>存款計息期 · ${offer.days} 日</p><strong>${esc(offer.reward_start)} → ${esc(offer.reward_end)}</strong></div><div><p>比較存款餘額日期</p><strong>${esc(offer.benchmark_date||'—')}</strong></div><div><p>登記截止</p><strong>${esc(offer.reg_end||'未有記錄')}</strong></div><div><p>獎賞最遲存入日</p><strong>${esc(offer.credit_date||'未有記錄')}</strong></div></div><p class="offer-note">${offer.excluded_months?.length?`⚠ 已登記 ${esc(offer.excluded_months.join('、'))} 推廣者不適用；亦須符合銀行其他限制。`:'合資格限制請參照該期條款。'}</p>${safeSource(offer.source_url)?`<a class="source-link" target="_blank" rel="noopener" href="${esc(offer.source_url)}">官方條款 ↗</a>`:'<span class="muted">來源：你嘅 Excel 紀錄</span>'}</section>`;
  $('teaser').textContent=`${offer.promo_month} 推廣 · ${closed?'登記已截止':'接受登記'}`;
  const selected=$('promo-select').value;
  $('promo-select').innerHTML=offers.map(o=>`<option value="${esc(o.id)}">${esc(o.promo_month)} · ${shortDate(o.reward_start)}–${shortDate(o.reward_end)}</option>`).join('');
  if(offers.some(o=>o.id===selected))$('promo-select').value=selected;
  $('member-list').innerHTML=(registrations.members||[]).map(m=>`<option value="${esc(m)}"></option>`).join('');
  $('registered-date').max=new Date().toLocaleDateString('en-CA');
  $('period-count').textContent=`${offers.length} 期`;
  const records=registrations.registrations;
  $('promotion-table').innerHTML=offers.map(o=>{
    const members=Object.values(records).filter(r=>r.promo_id===o.id&&r.status==='registered');
    return `<tr><td><strong>${esc(o.promo_month)}</strong><br><span class="muted">${o.source_kind==='official'?'官方驗證':'Excel 匯入'}</span></td><td>${esc(o.reward_start)}<br>${esc(o.reward_end)}</td><td>${o.days}</td><td>${esc(o.benchmark_date||'—')}</td><td>${esc(o.reg_end||'—')}</td>${labels.map(([k])=>`<td class="number">${pct(o.rates[k])}</td>`).join('')}<td>${esc((o.excluded_months||[]).join('、')||'—')}</td><td>${esc(o.previous_valid_end||'—')}</td><td>${esc(o.gap_days??'—')}</td><td>${members.length?members.map(m=>`<span class="member-chip" title="${esc(m.registered_on||'未記錄實際登記日期')}">${esc(m.member)}</span>`).join(''):'<span class="muted">未有記錄</span>'}</td><td><button class="edit-row" data-promo="${esc(o.id)}">記錄</button></td></tr>`;
  }).join('');
  document.querySelectorAll('[data-promo]').forEach(b=>b.addEventListener('click',()=>{$('promo-select').value=b.dataset.promo;$('registration-form').scrollIntoView({behavior:'smooth',block:'center'});$('member-input').focus();}));
}
function safeSource(url){try{const u=new URL(url);return u.protocol==='https:'&&(u.hostname==='go.dbs.com'||u.hostname==='www.dbs.com.hk');}catch{return false;}}

function render(){
  $('updated').textContent=data.updated_at?`最近更新 ${new Date(data.updated_at).toLocaleString('zh-HK',{timeZone:'Asia/Hong_Kong',hour12:false})} · 香港時間`:'未有每日資料更新紀錄';
  $('today').textContent=new Date().toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'Asia/Hong_Kong'});
  renderLoans();renderMargin();renderMarkets();renderEsaver();renderWarnings();
  const meetings=(data.fedwatch||[]).filter(m=>new Date(m.meeting)>=new Date(new Date().toDateString())).slice(0,4);
  $('outlook').innerHTML=meetings.length?meetings.map(m=>`<div class="outlook-card"><p>${esc(m.meeting)}</p><strong>${esc(m.most_likely)}%</strong><p>機率 ${pct(m.most_likely_pct,1)}</p><div class="prob-bar"><span style="width:${Math.max(0,Math.min(100,m.most_likely_pct))}%"></span></div></div>`).join(''):'<p class="muted">本次未有已驗證議息機率。</p>';
  const forwards=data.hkd_forwards||[];
  $('forwards').innerHTML=forwards.length?forwards.map(f=>`<div class="outlook-card"><p>${esc(f.tenor)}</p><strong>${esc(f.forward_points)}</strong><p>遠期點子</p></div>`).join(''):'<p class="muted">本次未有已驗證遠期匯價。</p>';
  $('forward-date').textContent=forwards.length?`${data.health?.hkd_forwards?.ok===false?'⚠ 本次更新失敗，顯示上次有效紀錄 · ':''}官方資料日期 ${forwards[0].date} · 月度統計有公布延遲 · 每點為 0.0001 港元兌 1 美元的匯價差`:'金管局月度統計 · 與利率嘅單位不同';
  $('footer-status').textContent=`家人紀錄更新：${registrations.synced_at?new Date(registrations.synced_at).toLocaleTimeString('zh-HK',{hour12:false}):'Excel 匯入'}`;

  navigate();
}

async function getJSON(path){
  const r=await monitorHTTP.send(`${path}?t=${Date.now()}`,{cache:'no-store'});
  if(!r.ok)throw new Error(`資料讀取失敗（HTTP ${r.status}）；請重新登入或更新頁面。`);
  return r.json();
}
async function load(){
  $('refresh').disabled=true;
  try{
    const values=[await getJSON('data.json'),await getJSON('registrations.json')];
    data=values[0];
    if(!registrations||values[1].sync_errors?.length||values[1].version>=registrations.version)registrations=values[1];
    if(!Array.isArray(data.loans)||!Array.isArray(data.promotions)||!registrations.registrations)throw new Error('監察資料格式不完整；已保留現有畫面。');
    $('load-error').hidden=true;render();
    if(location.hash==='#ib-margin'&&!marginLinkOpened){$('ib-margin').scrollIntoView();marginLinkOpened=true;}
  }catch(error){$('load-error').hidden=false;$('load-error').textContent=error.message;}
  finally{$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',load);
$('margin-currency').addEventListener('change',()=>{$('margin-amount').value=$('margin-currency').value==='HKD'?'1000000':'100000';renderMarginCalculator();});
$('margin-amount').addEventListener('input',()=>{if(data)renderMarginCalculator();});
document.querySelectorAll('#loan-range button').forEach(b=>b.addEventListener('click',()=>{loanDays=Number(b.dataset.days);document.querySelectorAll('#loan-range button').forEach(x=>x.classList.toggle('selected',x===b));renderLoans();renderMarkets();}));
document.querySelectorAll('#market-group button').forEach(b=>b.addEventListener('click',()=>{group=b.dataset.group;document.querySelectorAll('#market-group button').forEach(x=>x.classList.toggle('selected',x===b));renderMarkets();}));
function fillRegistration(){
  const key=`${$('promo-select').value}|${$('member-input').value.trim()}`;
  const record=registrations?.registrations?.[key];
  $('status-select').value=record?.status||'registered';$('registered-date').value=record?.registered_on||'';
}
$('member-input').addEventListener('change',fillRegistration);$('promo-select').addEventListener('change',fillRegistration);
const saveFamilyRecord=registrationSaver.createSaver({send:(...args)=>monitorHTTP.send(...args),storage:sessionStorage,makeId:()=>crypto.randomUUID()});
$('registration-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!data||!registrations)return;
  const member=$('member-input').value.trim();
  if(!member){$('save-status').textContent='請填寫家人名字。';return;}
  const fields={promo_id:$('promo-select').value,member,status:$('status-select').value,registered_on:$('registered-date').value||null};
  $('save-button').disabled=true;$('save-status').textContent='正在保存…';
  try{
    const saved=await saveFamilyRecord(fields);
    if(saved.sync_errors?.length||saved.version>=registrations.version)registrations=saved;
    renderEsaver();renderWarnings();
    $('save-status').textContent='已保存，重新開啟或在其他裝置更新頁面即可見到。';
  }catch(error){$('save-status').textContent=error.message;}
  finally{$('save-button').disabled=false;}
});
navigate();load();
