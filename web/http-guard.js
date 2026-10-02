'use strict';
// All app requests share the same browser cooldown and cross-tab send lock.
window.monitorHTTP=(()=>{
  const key='carelogic-r-monitor-http-cooldown';
  let autoLoad=true;
  const read=()=>JSON.parse(localStorage.getItem(key)||'{}');
  const save=value=>localStorage.setItem(key,JSON.stringify(value));
  function refusal(response){
    const previous=read(), strikes=(previous.strikes||0)+1, now=Date.now();
    const header=response.headers.get('Retry-After');
    const duration=header?(Number.isFinite(Number(header))?Number(header)*1000:Date.parse(header)-now):0;
    const base=[0,401,403].includes(response.status)?900000:86400000;
    const cooldown=Math.max(base*2**Math.min(strikes-1,5),(previous.duration||0)*2,Number.isFinite(duration)?duration+60000:0);
    const until=now+cooldown;
    save({strikes,until,duration:cooldown});autoLoad=false;
    throw new Error(`伺服器要求停止呼叫（HTTP ${response.status||'登入跳轉'}）；冷卻至 ${new Date(until).toLocaleString('zh-HK')}。表格內容保留，冷卻後請先確認登入。`);
  }
  async function send(path,options={}){
    if(!navigator.locks)throw new Error('瀏覽器無法提供共享呼叫鎖；已停止網絡呼叫，請用支援的新版瀏覽器。');
    return navigator.locks.request(key,async()=>{
      const state=read();
      if(state.until>Date.now())throw new Error(`呼叫冷卻至 ${new Date(state.until).toLocaleString('zh-HK')}；表格內容保留。`);
      const method=(options.method||'GET').toUpperCase(), attempts=method==='GET'?2:1;
      for(let attempt=0;attempt<attempts;attempt++){
        let response;
        try{response=await fetch(path,{...options,redirect:'manual'});}
        catch(error){
          if(attempt+1<attempts){await new Promise(resolve=>setTimeout(resolve,2000+Math.random()*500));continue;}
          throw new Error(method==='GET'?'網絡連線失敗；有上限的修復未成功，表格內容保留。':'保存送達不確定；已停止自動重送，表格內容保留。');
        }
        if(response.type==='opaqueredirect'||(response.status>=300&&response.status<400)||([400,404,422].includes(response.status)===false&&response.status>=400&&response.status<500))refusal(response);
        if(response.ok&&response.headers.get('Content-Type')?.includes('text/html'))refusal(response);
        if(response.status>=500&&attempt+1<attempts){await new Promise(resolve=>setTimeout(resolve,2000+Math.random()*500));continue;}
        if([400,404,422].includes(response.status))autoLoad=false;
        if(response.ok){autoLoad=true;}
        return response;
      }
    });
  }
  return {send,canAutoLoad:()=>autoLoad&&!(read().until>Date.now())};
})();
