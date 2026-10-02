/* Calculate each portion of a borrowing balance using its own published tier. */
(function(root){
  'use strict';
  function calculateMargin(item,amount){
    if(!item||!['HKD','USD'].includes(item.currency)||!Array.isArray(item.tiers)||!item.tiers.length)throw new Error('未有完整 IB 孖展利率。');
    if(!Number.isFinite(amount)||amount<=0||!Number.isSafeInteger(Math.round(amount*100)))throw new Error('請輸入大於零嘅有效借款金額。');
    let covered=0,weighted=0;const segments=[];
    for(const tier of item.tiers){
      if(tier.lower!==covered||!Number.isFinite(tier.rate)||tier.rate<0||(tier.upper!==null&&tier.upper<=tier.lower))throw new Error('IB 分級資料不完整，無法試算。');
      const part=Math.max(0,Math.min(amount,tier.upper??amount)-tier.lower);
      if(part>0){
        if(!Array.isArray(tier.notes))throw new Error('IB 大額借款條款未完整載入。');
        if(tier.notes.length)throw new Error(`超過 ${item.currency} ${tier.lower.toLocaleString('en')} 涉及大額附加費或個別條款，須由 IB 確認後計算。`);
        weighted+=part*tier.rate;segments.push({amount:part,rate:tier.rate});
      }
      covered=tier.upper;
      if(tier.upper===null||amount<=tier.upper)break;
    }
    if(segments.reduce((sum,s)=>sum+s.amount,0)!==amount)throw new Error('IB 借款級別未涵蓋輸入金額。');
    const dayBasis=item.currency==='HKD'?365:360;
    return {rate:weighted/amount,dailyInterest:weighted/100/dayBasis,dayBasis,segments};
  }
  const api={calculateMargin};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.marginMath=api;
})(typeof globalThis==='object'?globalThis:this);
