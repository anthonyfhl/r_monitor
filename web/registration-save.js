(function(root){
  'use strict';
  function createSaver({send,storage,makeId}){
    return async function save(fields){
      const key='esaver-unconfirmed-save';
      const fingerprint=JSON.stringify(fields);
      const previous=JSON.parse(storage.getItem(key)||'null');
      const payload=previous?.fingerprint===fingerprint?previous.payload:{event_id:makeId(),...fields};
      // Keep the same token across lost replies and page reloads in this tab.
      storage.setItem(key,JSON.stringify({fingerprint,payload}));
      let response;
      try{
        response=await send('inbox',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'esaver_registration',payload})});
      }catch(error){
        throw new Error(`未能確認保存；資料仍在表格內。${error.message}`);
      }
      if(!response.ok){
        throw new Error(response.status>=500?'未能確認保存；資料仍在表格內，再次保存會核對同一筆提交。':`保存未完成（HTTP ${response.status}）；資料仍在表格內。`);
      }
      const result=await response.json();
      if(result.ok!==true||result.committed!==true||result.event_id!==payload.event_id||!result.registrations?.registrations||!Array.isArray(result.registrations.members)||!Number.isInteger(result.registrations.version)){
        throw new Error('未能確認保存；資料仍在表格內，再次保存會核對同一筆提交。');
      }
      storage.removeItem(key);
      return result.registrations;
    };
  }
  if(typeof module!=='undefined')module.exports={createSaver};
  else root.registrationSaver={createSaver};
})(globalThis);
