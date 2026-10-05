(function(root){
  'use strict';
  const DAY=86400000, MAX=10000000000000;
  const pad=n=>String(n).padStart(2,'0');
  function iso(value){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value)||new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)throw new Error('日期無效：'+value);
    return value;
  }
  const shift=(d,n)=>new Date(Date.parse(iso(d))+n*DAY).toISOString().slice(0,10);
  function cents(value){
    if(typeof value==='number'){
      if(!Number.isFinite(value)||Math.abs(value*100-Math.round(value*100))>0.01)throw new Error('金額最多兩個小數位。');
      value=String(value);
    }
    const text=String(value).normalize('NFKC').trim().replace(/^(?:HKD|HK\$|\$)\s*/i,'').replace(/港元$/,'').trim();
    const sign=text.startsWith('-')?-1:1,body=text.replace(/^[+-]/,'');
    const parts=body.match(/(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?:億|萬|千|百|[kKmM])?/g);
    if(!parts||parts.join('')!==body)throw new Error('金額未能辨認／逗號或小數位有誤：'+text);
    let result=0,last=Infinity;
    const units={億:1e8,萬:1e4,千:1e3,百:100,k:1e3,m:1e6};
    for(const part of parts){
      const unit=units[part.at(-1).toLowerCase()]||1;
      if(unit>=last)throw new Error('金額單位次序有誤：'+text);last=unit;
      const digits=part.replace(/[億萬千百kKmM]$/,'').replaceAll(',','').split('.');
      result+=(Number(digits[0])*100+Number((digits[1]||'').padEnd(2,'0')))*unit;
    }
    if(!Number.isSafeInteger(result)||result>MAX)throw new Error('金額超出可核對範圍。');
    return result*sign;
  }
  const datePattern=/(?<!\d)(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}(?!\d)|\d{1,2}月\d{1,2}(?:[日號]|(?!\d))|\d{1,2}[/\-]\d{1,2}(?!\d)|\d{1,2}[日號]|今天|今日|昨天|昨日|琴日|前天|前日)/g;
  function dateOf(token,{month,today}){
    if(/^(今天|今日|昨天|昨日|琴日|前天|前日)$/.test(token))return shift(today,/前/.test(token)?-2:/昨天|昨日|琴日/.test(token)?-1:0);
    let match=token.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if(match)return iso(`${match[1]}-${pad(match[2])}-${pad(match[3])}`);
    match=token.match(/^(\d{1,2})月(\d{1,2})[日號]?$/);
    if(match)return iso(`${month.slice(0,4)}-${pad(match[1])}-${pad(match[2])}`);
    match=token.match(/^(\d{1,2})[日號]$/);
    if(match)return iso(`${month}-${pad(match[1])}`);
    match=token.match(/^(\d{1,2})[/.-](\d{1,2})$/);
    if(match){
      const options=[];
      for(const [a,b] of [[match[1],match[2]],[match[2],match[1]]]){
        try{const d=iso(`${month.slice(0,4)}-${pad(a)}-${pad(b)}`);if(d>=shift(month+'-01',-14)&&d.slice(0,7)<=month&&!options.includes(d))options.push(d);}catch{ /* invalid orientation is not a date candidate */ }
      }
      if(options.length!==1)throw new Error('日期有歧義，請寫明「10月3日」或完整年月日：'+token);
      return options[0];
    }
    throw new Error('未能辨認日期：'+token);
  }
  const incoming=/存入|入帳|入賬|轉入|收入|收到|收咗|收款|入金|存款|入數|\b(?:deposit|credit|cr)\b/i;
  const outgoing=/轉走|轉出|支出|提款|提走|扣帳|扣賬|扣款|付款|付咗|取款|出金|\b(?:withdrawal|withdraw|debit|dr)\b/i;
  const moneyPattern=/[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:億|萬|千|百|[kKmM])?(?:\d+(?:\.\d+)?[萬千百])*/g;
  function parse(text,context){
    iso(context.today);iso(context.month+'-01');
    const result={anchor:null,transactions:[],noTransactionDates:[],remainderConfirmed:false,issues:[]};
    if(typeof text!=='string'||text.length>16000)throw new Error('內容最多 16,000 字。');
    const lines=text.replace(/[,，]\s*(?=(?:其餘|其他|其它|no other))/gi,'\n').replace(/[；。]/g,'\n').normalize('NFKC').split(/\r?\n|;/);
    lines.forEach((original,index)=>{
      if(!original.trim())return;
      // Split sentences at dates, while keeping several transactions under one date.
      const dates=[...original.matchAll(datePattern)],starts=dates.map(d=>d.index).filter(n=>n>0);
      const splits=[0,...starts,original.length].filter((n,i,a)=>!i||n!==a[i-1]);
      // Text before the first date belongs to it (e.g. "結餘 10月5日 100000").
      if(dates.length&&dates[0].index>0)splits.splice(1,1);
      for(let s=0;s<splits.length-1;s++){
        const line=original.slice(splits[s],splits[s+1]).trim();if(!line)continue;
        try{
          if(/^(?:其餘|其他|其它)(?:日子|日期|日|時間)?\s*(?:都|全部|均)?\s*(?:冇|沒有|無|沒)(?:其他)?(?:已入帳|已入賬)?交易[。.!！]?$/.test(line)||/^no other transactions[.!]?$/i.test(line)){
            result.remainderConfirmed=true;continue;
          }
          if(/待入帳|待入賬|未入帳|未入賬|處理中|pending/i.test(line))throw new Error('呢筆未入帳，請先移除；只用已反映在今日結餘嘅交易。');
          if(/冇|沒有|未|失敗|預計|將會|取消|撤銷|\b(?:cancelled|canceled|reversed|expected|failed|not)\b/i.test(line)&&!/^(?:.*?[日號]|今天|今日|昨天|昨日|琴日|前天|前日)\s*(?:冇|沒有|無|沒)交易[。.!！]?$/.test(line))throw new Error('呢筆交易未確定已完成，請只保留已入帳交易。');
          if(/USD|US\$|美元|人民幣|CNY|RMB|EUR|歐元|GBP|英鎊|JPY|日圓|日元|AUD|澳元|CAD|加元|SGD|新加坡元/i.test(line))throw new Error('呢頁只回填大新港元戶口，請移除其他貨幣交易。');
          const tokens=[...line.matchAll(datePattern)];
          if(tokens.length!==1)throw new Error('請寫明日期（例如「3號」或「今日」）。');
          const date=dateOf(tokens[0][0],context);
          if(date>context.today||date<shift(context.month+'-01',-14)||date.slice(0,7)>context.month)throw new Error('日期須在所選月份或月初所需上月 14 日內，並不可在未來。');
          const rest=(line.slice(0,tokens[0].index)+line.slice(tokens[0].index+tokens[0][0].length)).trim();
          const isBalance=/結餘|餘額|余额|\bbalance\b/i.test(rest);
          if(isBalance){
            if(incoming.test(rest)||outgoing.test(rest))throw new Error('結餘同交易請分開寫，避免混淆。');
            const amounts=[...rest.matchAll(moneyPattern)];
            if(amounts.length!==1)throw new Error('結餘需有一個明確金額。');
            const value=cents(amounts[0][0]);if(value<0)throw new Error('戶口結餘不可為負。');
            const leftover=rest.replace(amounts[0][0],'').replace(/大新|港元|HKD|HK\$|結餘|餘額|余额|目前|現在|現時|截至|戶口|帳戶|賬戶|日終|收市|\bbalance\b/gi,'').replace(/[\s,:$()（）]/g,'');
            if(leftover)throw new Error('結餘句子有未能辨認內容；日期、金額同交易請分開寫。');
            if(result.anchor)throw new Error('有多於一個結餘，請只保留用作倒推嗰筆。');
            result.anchor={date,cents:value};continue;
          }
          if(/^(?:冇|沒有|無|沒)交易[。.!！]?$/.test(rest)){result.noTransactionDates.push(date);continue;}
          const directions=[...rest.matchAll(/存入|入帳|入賬|轉入|收入|收到|收咗|收款|入金|存款|入數|轉走|轉出|支出|提款|提走|扣帳|扣賬|扣款|付款|付咗|取款|出金|\b(?:deposit|credit|cr|withdrawal|withdraw|debit|dr)\b/gi)];
          const amounts=[...rest.matchAll(moneyPattern)];
          if(!amounts.length)throw new Error('金額未能辨認，請寫數字（例如 5000 或 5千）。');
          if((directions.length>1||amounts.length>1)&&directions.length!==amounts.length)throw new Error('存入／支出同金額未能逐筆配對，請分開寫。');
          if(amounts.length>1&&!directions.length)throw new Error('同日多筆交易請逐筆寫明存入／支出。');
          const extracted=[];
          amounts.forEach((amount,i)=>{
            const direction=directions.length===amounts.length?directions[i]:directions.length===1?directions[0]:null;
            if(direction&&directions.length>1&&(direction.index>amount.index||i+1<directions.length&&amount.index>directions[i+1].index))throw new Error('交易文字未能逐筆配對，請分開寫。');
            let value=cents(amount[0]);
            if(!direction&&!/^[+-]/.test(amount[0]))throw new Error('未講明存入定支出，請加「存入／轉走」或正負號。');
            if(direction){
              const sign=outgoing.test(direction[0])?-1:1;
              if(/^[+-]/.test(amount[0])&&value!==0&&Math.sign(value)!==sign)throw new Error('正負號同存入／支出意思相反，請核對。');
              value=Math.abs(value)*sign;
            }
            extracted.push({date,cents:value,line:index+1});
          });
          // Extra numbers cannot be treated as descriptions or account identifiers.
          let leftover=rest;for(const amount of amounts)leftover=leftover.replace(amount[0],'');
          if(/[\d+-]/.test(leftover)||/結餘|餘額/.test(leftover))throw new Error('有未能配對嘅數字或金額，請只保留交易金額。');
          result.transactions.push(...extracted);
        }catch(error){result.issues.push({line:index+1,text:line,message:error.message});}
      }
    });
    if(!result.anchor)result.issues.push({line:0,text:'',message:'請加一筆結餘，例如「今日結餘 100000」。'});
    return result;
  }
  function reconstruct(parsed,{start,today,complete=false,allowDuplicates=false,existing={}}){
    iso(start);iso(today);
    if(parsed.issues.length)throw new Error('先更正未能辨認嘅句子。');
    const anchor=parsed.anchor;iso(anchor.date);
    if(start>anchor.date||anchor.date>today||Date.parse(anchor.date)-Date.parse(start)>44*DAY)throw new Error('倒推範圍無效或超過 45 日。');
    const nets={},seen=new Set();
    for(const row of parsed.transactions){
      iso(row.date);if(row.date<=start||row.date>anchor.date)throw new Error(`${row.date} 交易不在倒推所需範圍；要用呢筆交易，請將起點設為前一日。`);
      if(!Number.isSafeInteger(row.cents)||Math.abs(row.cents)>MAX)throw new Error('交易金額無效。');
      const key=row.date+'|'+row.cents;
      if(seen.has(key)&&!allowDuplicates)throw new Error(`${row.date} 有同額同方向交易，請確認係兩筆交易。`);
      seen.add(key);nets[row.date]=(nets[row.date]||0)+row.cents;
    }
    for(const d of parsed.noTransactionDates){
      if(d>start&&d<=anchor.date){if(parsed.transactions.some(row=>row.date===d))throw new Error(`${d} 同時寫咗交易同「冇交易」，請核對。`);nets[d]=0;}
    }
    const missing=[];
    for(let d=shift(start,1);d<=anchor.date;d=shift(d,1))if(!(d in nets)){if(complete||parsed.remainderConfirmed)nets[d]=0;else missing.push(d);}
    let balance=anchor.cents,known=true;const rows=[],conflicts=[];
    for(let d=anchor.date;d>=start;d=shift(d,-1)){
      if(balance<0||!Number.isSafeInteger(balance)||balance>MAX)throw new Error(`${d} 倒推出負數或超範圍結餘，請核對交易及結餘。`);
      const provisional=d===today,amount=known?balance/100:null,old=existing[d];
      if(!provisional&&amount!==null&&old!=null&&cents(old)!==balance)conflicts.push(d);
      rows.push({date:d,amount,net:nets[d]===undefined?null:nets[d]/100,provisional,previous:old??null});
      if(d>start){if(nets[d]===undefined)known=false;else balance-=nets[d];}
    }
    return {rows:rows.reverse(),missing,conflicts,net_changes:nets,ready:!missing.length};
  }
  const api={iso,shift,cents,parse,reconstruct};
  if(typeof module!=='undefined')module.exports=api;else root.dsbBackfill=api;
})(globalThis);
