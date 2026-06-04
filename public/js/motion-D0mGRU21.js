import{t as e}from"./objectSpread2-BHJFn0bq.js";function t(e){return{animationDuration:e,animationFillMode:`both`}}function n(n,r,i,a,o=!1){let s=o?`&`:``;return{[`
      ${s}${n}-enter,
      ${s}${n}-appear
    `]:e(e({},t(a)),{},{animationPlayState:`paused`}),[`${s}${n}-leave`]:e(e({},t(a)),{},{animationPlayState:`paused`}),[`
      ${s}${n}-enter${n}-enter-active,
      ${s}${n}-appear${n}-appear-active
    `]:{animationName:r,animationPlayState:`running`},[`${s}${n}-leave${n}-leave-active`]:{animationName:i,animationPlayState:`running`,pointerEvents:`none`}}}export{n as t};