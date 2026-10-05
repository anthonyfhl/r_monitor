(function(root){
  'use strict';
  const m=root.dsbBackfill,$=id=>document.getElementById('dsb-backfill-'+id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=v=>v===null?'未確認':v.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
  function mount({context,apply}){
    let parsed=null,result=null,capturedAt=null,reviewContext=null;
    const draftKey=()=> 'dsb-backfill-text-'+context().month;
    function reset(){
      parsed=null;result=null;$('review').hidden=true;$('apply').disabled=true;
      for(const id of ['complete','duplicates','overwrite','verified'])$(id).checked=false;
      $('status').textContent='';
    }
    function changed(){reset();sessionStorage.setItem(draftKey(),$('text').value);}
    function refresh(){
      reset();const ctx=context();$('text').value=sessionStorage.getItem(draftKey())||'';
      for(const id of ['text','start','preview'])$(id).disabled=false;
      $('start').value=ctx.start;$('start').min=m.shift(ctx.month+'-01',-14);$('start').max=ctx.today;
      $('help').textContent=ctx.start<ctx.month+'-01'?`月初計息需 ${ctx.start} 結餘，已將倒推起點設為嗰日；請一併列出月初至查閱時所有已入帳交易。`:'以所選月份月初為起點；只用同一大新港元戶口已入帳結餘及交易。';
    }
    function update(){
      result=null;$('apply').disabled=true;$('status').textContent='';
      try{
        if(!parsed)return;
        parsed.anchor={date:$('anchor-date').value,cents:m.cents($('anchor-amount').value)};
        if(parsed.anchor.cents<0)throw new Error('結餘不可為負。');
        const edited=parsed.transactions.map((row,i)=>{
          const date=$('transactions').querySelector(`[data-row="${i}"][data-field="date"]`).value;
          const amount=m.cents($('transactions').querySelector(`[data-row="${i}"][data-field="amount"]`).value);
          const direction=Number($('transactions').querySelector(`[data-row="${i}"][data-field="direction"]`).value);
          if(amount<0)throw new Error('交易金額請填正數，用存入／支出揀方向。');
          return {...row,date:m.iso(date),cents:amount*direction};
        });
        parsed.transactions=edited;
        const ctx=context();
        if(ctx.month!==reviewContext.month||ctx.today!==reviewContext.today)throw new Error('月份／香港日期已改變，請重新整理及預覽。');
        if($('start').value<m.shift(ctx.month+'-01',-14)||$('start').value.slice(0,7)>ctx.month||parsed.anchor.date.slice(0,7)!==ctx.month)throw new Error('結餘日期須在所選月份，起點最多可追溯上月 14 日。');
        result=m.reconstruct(parsed,{start:$('start').value,today:ctx.today,complete:$('complete').checked,allowDuplicates:$('duplicates').checked,existing:ctx.balances});
        $('balances').innerHTML=result.rows.map(r=>`<tr><td>${r.date}</td><td class="number">${r.date===$('start').value?'—':money(r.net)}</td><td class="number">${money(r.amount)}</td><td>${r.provisional?'今日暫定 · 錄入 '+new Date(capturedAt).toLocaleTimeString('zh-HK',{timeZone:'Asia/Hong_Kong',hour12:false}):r.amount===null?'需確認中間交易':result.conflicts.includes(r.date)?'將更正原有 '+money(r.previous):'倒推日終結餘'}</td></tr>`).join('');
        $('gaps').textContent=result.missing.length?'未確認交易日期：'+result.missing.join('、')+'。核對交易完整後，勾選下面確認。':'所需日期已列出交易或確認冇交易。';
        $('overwrite-label').hidden=!result.conflicts.length;
        $('overwrite-note').textContent=result.conflicts.length?`會更正 ${result.conflicts.length} 日已有結餘；原紀錄有備份。`:'';
        $('apply').disabled=!result.ready||!$('verified').checked||result.conflicts.length>0&&!$('overwrite').checked;
      }catch(error){$('balances').innerHTML='';$('gaps').textContent='';$('status').textContent=error.message;}
    }
    function renderTransactions(){
      $('transactions').innerHTML=parsed.transactions.map((r,i)=>`<tr><td><input type="date" data-row="${i}" data-field="date" aria-label="交易 ${i+1} 日期" value="${r.date}"></td><td><select data-row="${i}" data-field="direction" aria-label="交易 ${i+1} 方向"><option value="1" ${r.cents>=0?'selected':''}>存入</option><option value="-1" ${r.cents<0?'selected':''}>支出</option></select></td><td><input type="text" inputmode="decimal" data-row="${i}" data-field="amount" aria-label="交易 ${i+1} 金額" value="${Math.abs(r.cents)/100}"></td><td><button type="button" class="quiet-button" data-remove="${i}" aria-label="移除交易 ${i+1}">移除</button></td></tr>`).join('');
      $('transaction-count').textContent=`已整理 ${parsed.transactions.length} 筆交易 · 港元`;
      $('transactions').querySelectorAll('[data-row]').forEach(el=>el.addEventListener(el.tagName==='SELECT'?'change':'input',()=>{
        $('verified').checked=false;$('overwrite').checked=false;update();
      }));
      $('transactions').querySelectorAll('[data-remove]').forEach(el=>el.addEventListener('click',()=>{
        parsed.transactions.splice(Number(el.dataset.remove),1);$('verified').checked=false;$('overwrite').checked=false;renderTransactions();update();
      }));
    }
    $('text').addEventListener('input',changed);
    $('preview').addEventListener('click',()=>{
      reset();
      try{
        const ctx=context();reviewContext={month:ctx.month,today:ctx.today};capturedAt=new Date().toISOString();
        parsed=m.parse($('text').value,{month:ctx.month,today:ctx.today});
        if(parsed.issues.length){
          $('status').innerHTML=parsed.issues.map(i=>`<p>${i.line?'第 '+i.line+' 段「'+esc(i.text)+'」：':''}${esc(i.message)}</p>`).join('');parsed=null;return;
        }
        $('anchor-date').value=parsed.anchor.date;$('anchor-date').min=ctx.month+'-01';$('anchor-date').max=ctx.today;
        $('anchor-amount').value=parsed.anchor.cents/100;$('review').hidden=false;
        renderTransactions();update();
      }catch(error){$('status').textContent=error.message;}
    });
    for(const id of ['start','anchor-date','anchor-amount','complete','duplicates'])$(id).addEventListener(['complete','duplicates'].includes(id)?'change':'input',()=>{$('verified').checked=false;$('overwrite').checked=false;update();});
    for(const id of ['overwrite','verified'])$(id).addEventListener('change',update);
    $('apply').addEventListener('click',()=>{
      update();if(!result||$('apply').disabled)return;
      try{
        const ctx=context(),provisional=parsed.anchor.date===ctx.today;
        apply({balances:Object.fromEntries(result.rows.filter(r=>!r.provisional).map(r=>[r.date,r.amount])),
          audit:{start_date:$('start').value,anchor_date:parsed.anchor.date,anchor_balance:parsed.anchor.cents/100,
            captured_at:capturedAt,net_changes:result.net_changes,confirmed_complete:true,provisional},provisional});
        $('review').hidden=true;parsed=null;result=null;
        $('status').textContent='已套用至本月草稿；請按「保存本月」。'+(provisional?'今日結餘保留為暫定，用於由今日起嘅預測。':'');
      }catch(error){$('status').textContent=error.message;}
    });
    return {refresh};
  }
  root.dsbBackfillUI={mount};
})(globalThis);
