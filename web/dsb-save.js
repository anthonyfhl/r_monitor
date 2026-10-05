(function(root){
  'use strict';
  function createSaver({send,storage,makeId}){
    return async fields=>{
      const key='dsb-unconfirmed-save',fingerprint=JSON.stringify(fields),previous=JSON.parse(storage.getItem(key)||'null');
      const payload=previous?.fingerprint===fingerprint?previous.payload:{event_id:makeId(),...fields};
      const body=JSON.stringify({kind:'dsb_month',payload});
      if(new TextEncoder().encode(body).length>8192)throw new Error('本月提交超出保存大小上限；請縮減預計資金變動，草稿已保留，未有送出。');
      storage.setItem(key,JSON.stringify({fingerprint,payload}));
      const response=await send('inbox',{method:'POST',headers:{'Content-Type':'application/json'},body});
      const result=await response.json();
      if(!response.ok||result.ok!==true||result.committed!==true||result.event_id!==payload.event_id||!Number.isInteger(result.dsb?.version)||!result.dsb?.balances||!result.dsb?.months)throw new Error(result.error||'未能確認保存；草稿已保留，再次保存會核對同一筆提交。');
      storage.removeItem(key);return result.dsb;
    };
  }
  if(typeof module!=='undefined')module.exports={createSaver};else root.dsbSaver={createSaver};
})(globalThis);
