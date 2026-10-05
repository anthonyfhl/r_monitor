(function(root){
  'use strict';
  const $=id=>document.getElementById('dsb-'+id),m=root.dsbMath;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const cash=v=>Number.isFinite(v)?'HK$'+v.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  const rate=v=>Number.isFinite(v)?v.toFixed(3)+'%':'—';
  const today=()=>new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Hong_Kong'});
  const zeroTasks=()=>({payroll:false,debit:0,credit:0,fx:0,fund:false,stock:0,vip1:false,vip2:false});
  let publicData,records,draft,month,health={},busy=false,dirty=false,lastResult;
  const saver=root.dsbSaver.createSaver({send:(...a)=>root.monitorHTTP.send(...a),storage:sessionStorage,makeId:()=>crypto.randomUUID()});
  const readNumber=id=>$(id).value.trim()===''?null:Number($(id).value);
  const backfill=root.dsbBackfillUI.mount({
    context(){
      let start=month+'-01';
      if(publicData&&draft?.record&&rule()?.balance_basis!=='entered')try{start=m.effectiveDate(start,publicData.calendar);}catch{ /* the ledger already exposes missing calendar evidence */ }
      return {month,today:today(),start,balances:mergedBalances()};
    },
    apply(value){
      gather();
      if(value.provisional&&draft.record.movements.some(move=>move.date<value.audit.anchor_date))throw new Error('預計資金變動有今日以前嘅交易，請先核對並更正資金計劃，再套用。');
      Object.assign(draft.balances,value.balances);draft.record.balance_backfill=value.audit;
      if(value.provisional){draft.record.planning_date=value.audit.anchor_date;draft.record.current_balance=value.audit.anchor_balance;}
      stash();renderForm();render();
    }
  });
  const rule=()=>publicData.catalog.rules[draft.record.rule_revision];
  function defaultMonth(value){
    const saved=records.months[value];if(saved)return structuredClone(saved);
    const enrollment=[...records.enrollments].filter(e=>e.registered&&e.effective_month<=value&&e.reward_end.slice(0,7)>=value).sort((a,b)=>b.effective_month.localeCompare(a.effective_month))[0];
    const offer=publicData.catalog.offers.find(o=>o.id===enrollment?.offer_id);
    const r=publicData.catalog.rules[offer?.revision];
    const planned=zeroTasks();if(r){planned.payroll=true;for(const k of ['debit','credit','fx','stock'])planned[k]=r.thresholds[k].at(-1);planned.vip1=true;planned.vip2=true;}
    const days=m.monthDates(value),asOf=value===today().slice(0,7)?today():value<today().slice(0,7)?m.shift(days.at(-1),1):days[0];
    return {offer_id:offer?.id||'',rule_revision:offer?.revision||'',account:'vip',actual:zeroTasks(),planned,
      basic_rate:null,costs:{debit:null,credit:null,fx:null,stock:null,other:null},receipts:{core:null,vip:null,basic:null},
      planning_date:asOf,current_balance:null,eligible_from:days[0],movements:[],terms_confirmed:enrollment?.terms_confirmed||false,
      registered:!!enrollment,registered_on:enrollment?.registered_on||null};
  }
  function stash(){
    sessionStorage.setItem('dsb-draft-'+month,JSON.stringify(draft));dirty=true;
    $('save-status').textContent='有未保存更改';
  }
  function chooseMonth(value){
    if(draft&&dirty)stash();
    month=value;m.monthDates(month);
    const saved=sessionStorage.getItem('dsb-draft-'+month);
    draft=saved?JSON.parse(saved):{base_version:records.version,record:defaultMonth(month),balances:{}};
    dirty=!!saved;
    $('month').value=month;
    renderForm();render();
    $('save-status').textContent=saved?'已還原未保存草稿；保存前會核對版本。':records.months[month]?'已讀取保存紀錄':'新月份草稿；填寫後保存';
  }
  function gather(){
    const r=draft.record;
    r.planning_date=$('asof').value;r.current_balance=readNumber('opening');r.account=$('account').value;
    r.basic_rate=readNumber('basic');r.eligible_from=$('eligible').value;r.terms_confirmed=$('confirmed').checked;
    r.registered=$('registered').checked;r.registered_on=$('registered-on').value||null;
    r.movements=m.parseLines($('movements').value,month,{movement:true});
    for(const key of ['debit','credit','fx','stock','other'])r.costs[key]=readNumber('cost-'+key);
    for(const key of ['core','vip','basic'])r.receipts[key]=readNumber('received-'+key);
    for(const mode of ['actual','planned']){
      for(const key of ['payroll','vip1','vip2'])r[mode][key]=$(`${mode}-${key}`).value==='yes';
      for(const key of ['debit','credit','stock'])r[mode][key]=Number($(`${mode}-${key}`).value);
      const fx=$(`${mode}-fx`).value;r[mode].fund=fx==='fund';r[mode].fx=fx==='fund'?0:Number(fx);
    }
  }
  function fields(){
    gather();return {base_version:draft.base_version,month,record:draft.record,balances:draft.balances};
  }
  function mergedBalances(){const result={...records.balances};for(const [d,v] of Object.entries(draft.balances)){if(v===null)delete result[d];else result[d]=v;}return result;}
  function input(){return {month,asOf:draft.record.planning_date,rule:rule(),settings:draft.record,balances:mergedBalances(),calendar:publicData.calendar,movements:draft.record.movements,currentBalance:draft.record.current_balance};}
  function taskSelect(id,options,value){return `<select id="dsb-${id}">${options.map(([v,label])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${esc(label)}</option>`).join('')}</select>`;}
  function renderTasks(){
    const r=rule(),tiers=r?.thresholds||{debit:[2000,5000,10000],credit:[3000],fx:[10000],stock:[30000,50000],fund:100000};
    const options={payroll:[['no','未記錄'],['yes','合資格出糧已完成']],debit:[[0,'未記錄'],...tiers.debit.map(v=>[v,`累計 ≥ $${v.toLocaleString('en')}`])],
      credit:[[0,'未記錄'],...tiers.credit.map(v=>[v,`累計 ≥ $${v.toLocaleString('en')}`])],
      fx:[[0,'未記錄'],[tiers.fx[0],`單筆兌換 ≥ $${tiers.fx[0].toLocaleString('en')}`],['fund',`單筆基金 ≥ $${tiers.fund.toLocaleString('en')}`]],
      stock:[[0,'未記錄'],...tiers.stock.map(v=>[v,`單筆 ≥ $${v.toLocaleString('en')}`])],vip1:[['no','未記錄'],['yes','合資格服務／簽賬']],vip2:[['no','未記錄'],['yes','持有股票／合資格投資']]};
    const names={payroll:'出糧資格',debit:'扣賬卡',credit:'信用卡',fx:'外幣／基金',stock:'證券交易',vip1:'VIP 額外種類 1',vip2:'VIP 額外種類 2'};
    $('tasks').innerHTML=Object.entries(names).map(([key,label])=>`<tr><td>${label}</td>${['actual','planned'].map(mode=>{
      const tasks=draft.record[mode],value=['payroll','vip1','vip2'].includes(key)?(tasks[key]?'yes':'no'):key==='fx'&&tasks.fund?'fund':tasks[key];
      const available=[...options[key]];if(!available.some(o=>String(o[0])===String(value)))available.push([value,`已存金額 ${value}`]);
      return `<td>${taskSelect(mode+'-'+key,available,value)}</td>`;
    }).join('')}</tr>`).join('');
    $('tasks').querySelectorAll('select').forEach(el=>el.addEventListener('change',changed));
  }
  function renderForm(){
    const r=draft.record,available=Object.values(publicData.catalog.rules).filter(x=>x.reward_start.slice(0,7)<=month&&x.reward_end.slice(0,7)>=month);
    $('offer').innerHTML='<option value="">選擇已登記期別</option>'+available.map(o=>`<option value="${esc(o.revision)}">${esc(o.id)} · ${o.source_kind==='excel'?'Excel 歷史':o.reward_start+' 至 '+o.reward_end}</option>`).join('');
    $('offer').value=r.rule_revision;$('account').value=r.account;$('asof').value=r.planning_date;$('asof').min=month+'-01';$('asof').max=m.shift(m.monthDates(month).at(-1),1);
    $('opening').value=r.current_balance??'';$('basic').value=r.basic_rate??'';$('eligible').value=r.eligible_from||month+'-01';
    $('confirmed').checked=!!r.terms_confirmed;
    const enrolled=records.enrollments.find(e=>e.offer_id===r.offer_id);
    $('registered').checked=r.registered??!!enrolled?.registered;$('registered-on').value=r.registered_on??enrolled?.registered_on??'';
    $('movements').value=r.movements.map(v=>`${v.date} ${v.amount>=0?'+':''}${v.amount}`).join('\n');
    for(const [k,v] of Object.entries(r.costs))$('cost-'+k).value=v??'';
    for(const k of ['core','vip','basic'])$('received-'+k).value=r.receipts?.[k]??'';
    $('fill-start').value=month+'-01';$('fill-end').value=month===today().slice(0,7)?m.shift(today(),-1):m.monthDates(month).at(-1);
    $('saved-months').innerHTML='<option value="">開啟已有月份</option>'+Object.keys(records.months).sort().reverse().map(v=>`<option value="${v}">${v}</option>`).join('');
    renderTasks();
    backfill.refresh();
  }
  function drawChart(result){
    if(!result){$('chart').innerHTML='<p class="muted dsb-empty">補齊已過日期嘅結餘後，顯示逐日累計優惠利息及月底預測。</p>';return;}
    let total=0;const points=result.rows.map(r=>({...r,total:total+=r.core})),top=Math.max(rule().cap*1.12,total*1.08,1);
    const x=i=>48+i*860/Math.max(1,points.length-1),y=v=>176-v/top*145;
    let svg='<svg viewBox="0 0 940 220" role="img" aria-label="本月逐日累計出糧優惠利息，港元"><title>累計出糧優惠利息，港元；未封頂曲線用於顯示超額</title>';
    for(let i=0;i<=3;i++){const value=top*i/3;svg+=`<line class="gridline" x1="48" x2="908" y1="${y(value)}" y2="${y(value)}"/><text x="40" y="${y(value)+4}" text-anchor="end">${Math.round(value).toLocaleString('en')}</text>`;}
    svg+=`<line x1="48" x2="908" y1="${y(rule().cap)}" y2="${y(rule().cap)}" stroke="#ebbd67" stroke-dasharray="6 4"/><text x="908" y="${y(rule().cap)-6}" text-anchor="end">每月上限 ${cash(rule().cap)}</text>`;
    for(let i=1;i<points.length;i++)svg+=`<path d="M${x(i-1)},${y(points[i-1].total)} L${x(i)},${y(points[i].total)}" fill="none" stroke="${points[i].date>=draft.record.planning_date?'#879ec5':'#64cbb1'}" stroke-width="3" ${points[i].date>=draft.record.planning_date?'stroke-dasharray="5 3"':''}/>`;
    [0,Math.floor(points.length/2),points.length-1].forEach(i=>svg+=`<text x="${x(i)}" y="204" text-anchor="middle">${points[i].date.slice(5)}</text>`);
    $('chart').innerHTML=svg+'</svg><div class="dsb-chart-key">實線：已記結餘試算 · 虛線：未來結餘預測 · 港元</div>';
  }
  function renderLedger(result){
    const balances=mergedBalances(),r=rule(),cal=publicData.calendar,rows=result?.rows||[],days=m.monthDates(month);
    let anchor;
    try{anchor=m.effectiveDate(days[0],cal);}catch{anchor=null;}
    const dates=anchor&&anchor<days[0]&&r?.balance_basis!=='entered'?[anchor,...days]:days;
    let cumulative=0,complete=true;
    $('ledger').innerHTML=dates.map(date=>{
      let red=false,source=date,calendarError='';
      try{red=m.holiday(date,cal);if(r?.balance_basis!=='entered')source=m.effectiveDate(date,cal);}catch(error){calendarError=error.message;}
      const future=date>=draft.record.planning_date,projection=rows.find(v=>v.date===date),actual=balances[date],effective=projection?.balance??balances[source];
      const interest=r&&Number.isFinite(effective)?m.daily(r,draft.record,draft.record[$('mode').value],effective,date).core:null;
      if(date.startsWith(month)){if(interest===null)complete=false;else cumulative+=interest;}
      const name=cal.names?.[date]||(new Date(date+'T00:00:00Z').getUTCDay()===0?'星期日':'');
      return `<tr class="${red?'dsb-holiday':''} ${future?'dsb-future':''}"><td><strong>${date.slice(5)}</strong><span class="dsb-day-note">${esc(name||['日','一','二','三','四','五','六'][new Date(date+'T00:00:00Z').getUTCDay()])}${date<days[0]?' · 月初追溯':''}</span></td><td><input aria-label="${date} 實際結餘" data-balance="${date}" type="number" min="0" step="0.01" value="${actual??''}" placeholder="${date>today()?'未來':'未填'}" ${date>today()?'disabled':''}></td><td class="number">${cash(effective)}<span class="dsb-day-note">${calendarError?esc(calendarError):source!==date?'沿用 '+source.slice(5):projection?.projected?'預測':'當日結餘'}</span></td><td class="number">${cash(interest)}</td><td class="number">${date.startsWith(month)&&complete?cash(Math.min(cumulative,r?.cap??0)):'—'}</td></tr>`;
    }).join('');
    $('ledger').querySelectorAll('[data-balance]').forEach(el=>el.addEventListener('change',()=>{draft.balances[el.dataset.balance]=el.value===''?null:Number(el.value);draft.record.balance_backfill=null;stash();render();}));
  }
  function renderPeriods(){
    const offers=[...publicData.catalog.offers].sort((a,b)=>b.reward_start.localeCompare(a.reward_start));
    const start=Math.min(...offers.map(o=>Date.parse(o.reward_start))),end=Math.max(...offers.map(o=>Date.parse(o.reward_end)))+DAY,span=end-start;
    $('periods').innerHTML=offers.map(o=>{
      const enrolled=records.enrollments.find(e=>e.offer_id===o.id&&e.registered),left=(Date.parse(o.reward_start)-start)/span*100,width=(Date.parse(o.reward_end)+DAY-Date.parse(o.reward_start))/span*100;
      return `<tr><td><strong>${esc(o.id)}</strong></td><td>${esc(o.reward_start)} → ${esc(o.reward_end)}<div class="dsb-period-track" title="各行使用相同日期刻度"><i style="margin-left:${left}%;width:${width}%"></i></div></td><td>${enrolled?'已登記':'未記錄登記'}${o.revision?'':'・息率待核對'}</td><td>${o.max_core_rate?rate(o.max_core_rate):'—'}</td></tr>`;
    }).join('');
  }
  const DAY=86400000;
  function render(){
    if(!draft)return;
    const r=rule(),warnings=[];lastResult=null;
    const enrollment=draft.record.registered?{offer_id:draft.record.offer_id,reward_end:r?.reward_end,registered_on:draft.record.registered_on}:null;
    $('enrollment').textContent=enrollment?`${enrollment.offer_id} 期已登記 · 加息至 ${enrollment.reward_end}${enrollment.registered_on?'':' · 實際登記日未填'}`:'所選月份尚未記錄登記';
    if(r?.scope==='new_customer'&&!draft.record.terms_confirmed)warnings.push('重新登記條款尚未獨立核對；現以同期香港公開新客條款試算。核對後可在期別設定確認。');
    if(r?.source_kind==='excel'||r?.source_kind==='bank_scan_mirror')warnings.push(r.scope_note);
    if(r?.source_kind!=='excel'&&!draft.record.registered_on)warnings.push('未填實際登記日；首次月份暫按所填「優惠開始計息日」試算，請按銀行確認日期核對。');
    if(r&&r.source_kind!=='excel'&&!draft.record.registered)warnings.push('所選期別尚未記錄登記，以下只屬假設試算。');
    if(!draft.record.basic_rate&&draft.record.basic_rate!==0)warnings.push('基本存款年利率未填，總利息及淨回報暫不計算；出糧優惠倒算仍可使用。');
    for(const key of ['dsb','dsb_calendar'])if(health[key]?.ok===false)warnings.push((key==='dsb'?'大新條款':'香港假期')+'更新失敗：'+(health[key].repair||health[key].error));
    warnings.push(...(records.sync_errors||[]));
    if(dirty&&draft.base_version!==records.version)warnings.push('已保存紀錄有較新版本；你的草稿仍在，需核對後再保存。');
    $('notes').innerHTML=warnings.map(v=>`<p>${esc(v)}</p>`).join('');$('notes').hidden=!warnings.length;
    const tasks=draft.record[$('mode').value];let solved,errorMessage='';
    try{
      const value=input();solved=m.solve(value,tasks);
      try{lastResult=m.calculate(value,tasks);}catch(error){errorMessage=error.message;}
    }catch(error){errorMessage=error.message;}
    $('calc-error').textContent=errorMessage;$('calc-error').hidden=!errorMessage;
    const result=lastResult||solved?.result,card=(label,value,note)=>`<article class="dsb-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`;
    $('summary').innerHTML=card('截至調整日前優惠利息',cash(result?.pastCore),'按所選任務估算，非銀行已派息')+card('尚餘優惠額度',cash(result?.remaining),'每月出糧優惠上限 '+cash(r?.cap))+
      card('調整後應有總結餘',cash(solved?.opening),'包含預計提款／入金，目標用盡優惠')+
      card(solved?.adjustment<0?'可減少結餘':'可以再加資金',cash(Number.isFinite(solved?.adjustment)?Math.abs(solved.adjustment):null),solved?.status==='cap_reached'?'優惠額度已到頂；保留提款所需資金':solved?.status==='unreachable'?'未有合資格加息／所需金額超出試算範圍':solved?.status==='no_remaining_days'?'本月已沒有可調整計息日':'相對輸入嘅調整前結餘');
    const projected=lastResult;
    $('totals').innerHTML=[['出糧優惠',projected?.core],['VIP 額外',projected?.vip],['基本利息',projected?.basic],['總利息',projected?.gross],['扣成本後',projected?.net]].map(([label,v])=>`<div><span>${label}</span><strong>${cash(v)}</strong></div>`).join('');
    $('projection-note').textContent=`按${$('mode').value==='planned'?'預計月底完成任務':'已記錄完成任務'}及目前資金計劃預測。${projected?.overCap>0?'超出上限前優惠利息 '+cash(projected.overCap)+'；超額資金只增加其他適用利息。':''}${projected?.cost===null?' 成本未填齊，淨回報未計。':''}${Number.isFinite(projected?.netAnnualized)?' 按每日計息本金折算，扣成本後估算年化 '+rate(projected.netAnnualized)+'。':''}`;
    drawChart(projected);renderLedger(projected);renderPeriods();
    const received=draft.record.receipts,actualTotal=received&&Object.values(received).every(Number.isFinite)?Object.values(received).reduce((a,b)=>a+b,0):null;
    const isClosed=draft.record.planning_date>m.monthDates(month).at(-1);
    let actualEstimate=null;
    let reconciliationError='';
    if(isClosed)try{actualEstimate=m.calculate(input(),draft.record.actual).gross;}catch(error){reconciliationError=error.message;}
    $('reconcile').textContent=actualTotal===null?'填齊三類實收利息後核對；零利息請填 0。':!isClosed?'月結核對需將調整日期設為下月首日，並補齊本月每日紀錄。':actualEstimate===null?'估算資料未齊，暫不能核對實收差額。'+reconciliationError:`實收 ${cash(actualTotal)}｜按已完成任務估算 ${cash(actualEstimate)}｜差額 ${cash(actualTotal-actualEstimate)}`;
    const audit=records.import?.audit?.find(a=>a.month===month);
    $('import-note').textContent=audit?`Excel 匯入 ${audit.known_days}/${audit.expected_days} 日。原表優惠合計 ${cash(audit.original_cached_sum)}；逐日重算未封頂 ${cash(audit.recomputed_core_before_cap)}。${audit.complete?'':'原表缺日仍保留為未填。'}`:'';
    const snapshot=draft.record.balance_backfill;
    if(snapshot?.provisional)$('import-note').textContent+=` ${snapshot.anchor_date} 暫定結餘 ${cash(snapshot.anchor_balance)}（錄入 ${new Date(snapshot.captured_at).toLocaleTimeString('zh-HK',{timeZone:'Asia/Hong_Kong',hour12:false})}），未當作最終日終紀錄。`;
  }
  function changed(){try{gather();const audit=draft.record.balance_backfill;if(audit?.provisional&&(audit.anchor_date!==draft.record.planning_date||audit.anchor_balance!==draft.record.current_balance))draft.record.balance_backfill=null;stash();render();}catch(error){$('calc-error').hidden=false;$('calc-error').textContent=error.message;}}
  async function read(path){const response=await root.monitorHTTP.send(path+'?t='+Date.now(),{cache:'no-store'});if(!response.ok)throw new Error(`大新紀錄讀取失敗（HTTP ${response.status}）`);return response.json();}
  async function load(force=false){
    if(busy)return;busy=true;
    try{
      const latestPublic=await read('dsb-public.json'),latestRecords=await read('dsb-records.json');
      if(!latestPublic.catalog?.rules||!latestRecords.months||!latestRecords.balances)throw new Error(latestRecords.error||'大新資料結構未完整，現有草稿已保留。');
      publicData=latestPublic;records=latestRecords;
      if(!month)chooseMonth(today().slice(0,7));else if(force){draft=null;chooseMonth(month);}else render();
      $('load-error').hidden=true;
    }catch(error){$('load-error').hidden=false;$('load-error').textContent=error.message;}finally{busy=false;}
  }
  function mount(){
    $('month').addEventListener('change',()=>{try{chooseMonth($('month').value);}catch(error){$('load-error').hidden=false;$('load-error').textContent=error.message;}});
    $('saved-months').addEventListener('change',()=>{if($('saved-months').value)chooseMonth($('saved-months').value);});
    $('mode').addEventListener('change',render);
    $('offer').addEventListener('change',()=>{const r=publicData.catalog.rules[$('offer').value];if(!r)return;const e=records.enrollments.find(e=>e.offer_id===r.id);draft.record.rule_revision=r.revision;draft.record.offer_id=r.id;draft.record.terms_confirmed=!!e?.terms_confirmed;draft.record.registered=!!e?.registered;draft.record.registered_on=e?.registered_on||null;stash();renderForm();render();});
    for(const id of ['account','asof','opening','basic','eligible','confirmed','registered','registered-on','movements',...['debit','credit','fx','stock','other'].map(k=>'cost-'+k),...['core','vip','basic'].map(k=>'received-'+k)])$(id).addEventListener('change',changed);
    $('save').addEventListener('click',async()=>{
      $('save').disabled=true;
      try{const payload=fields();stash();$('save-status').textContent='正在核對並保存…';const saved=await saver(payload);records=saved;draft.base_version=saved.version;dirty=false;sessionStorage.removeItem('dsb-draft-'+month);$('save-status').textContent='已保存，可在其他裝置讀取。';render();}
      catch(error){$('save-status').textContent=error.message;}finally{$('save').disabled=false;}
    });
    $('reload').addEventListener('click',()=>load(true));
    $('rebase').addEventListener('click',()=>{if(!records)return;draft.base_version=records.version;stash();$('save-status').textContent='已按目前已讀取版本保留草稿；請核對後保存。';render();});
    $('paste').addEventListener('click',()=>{try{for(const row of m.parseLines($('bulk').value,month))draft.balances[row.date]=row.amount;draft.record.balance_backfill=null;stash();render();$('bulk-status').textContent='已套用至草稿，請保存。';}catch(error){$('bulk-status').textContent=error.message;}});
    $('fill').addEventListener('click',()=>{try{const start=m.iso($('fill-start').value),end=m.iso($('fill-end').value),amount=readNumber('fill-amount');if(start>end||!start.startsWith(month)||!end.startsWith(month)||end>today()||!Number.isFinite(amount)||amount<0)throw new Error('請輸入本月已過日期範圍及非負結餘。');for(let d=start;d<=end;d=m.shift(d,1))draft.balances[d]=amount;draft.record.balance_backfill=null;stash();render();$('bulk-status').textContent='已按你確認嘅不變結餘填入草稿，請保存。';}catch(error){$('bulk-status').textContent=error.message;}});
  }
  mount();root.dsbPage={show(value){health=value||{};if(!records)load();else render();},refresh(){return load(true);}};
})(globalThis);
