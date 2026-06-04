import{t as e}from"./asyncToGenerator-CGBZTlHR.js";import{d as t,i as n}from"./store-BAGNW_Mm.js";import{Fn as r,Kn as i,On as a,an as o,br as s,dn as c,fr as l,in as u,jn as d,on as f,pn as p,rr as m,un as h}from"../jse/index-index-BbYoHiE2.js";import{o as g}from"./dist-Bt0lXR2K.js";import{t as _}from"./page-9VUG2zE8.js";var v=p({__name:`index`,setup(p){let v=m(null),y=m(``),b=m(!1);function x(){return S.apply(this,arguments)}function S(){return S=e(function*(){b.value=!0;try{v.value=yield n()}finally{b.value=!1}}),S.apply(this,arguments)}function C(){return w.apply(this,arguments)}function w(){return w=e(function*(){if(!window.confirm(`重置后旧 Token 会立即失效，确认继续？`))return;let e=yield t();y.value=e.token,v.value=e,g.success(`调用 Token 已生成，请立即保存明文 Token`)}),w.apply(this,arguments)}function T(){var e;y.value&&((e=navigator.clipboard)==null||e.writeText(y.value),g.success(`Token 已复制`))}return a(x),(e,t)=>{let n=r(`a-step`),a=r(`a-steps`),p=r(`a-card`),m=r(`a-col`),g=r(`a-typography-title`),S=r(`a-typography-paragraph`),w=r(`a-typography`),E=r(`a-tab-pane`),D=r(`a-alert`),O=r(`a-descriptions-item`),k=r(`a-descriptions`),A=r(`a-typography-text`),j=r(`a-button`),M=r(`a-space`),N=r(`a-collapse-panel`),P=r(`a-collapse`),F=r(`a-tabs`),I=r(`a-row`);return d(),o(l(_),{"content-class":`space-y-4`,description:`面向用户和外部系统接入方的操作说明、API 入口和异常处理规则。`,title:`使用文档`},{default:i(()=>[c(I,{gutter:[16,16]},{default:i(()=>[c(m,{lg:8,xs:24},{default:i(()=>[c(p,{title:`快速流程`},{default:i(()=>[c(a,{direction:`vertical`,size:`small`},{default:i(()=>[c(n,{title:`输入题目`,description:`填写题目、字数、文献数量和写作方向`}),c(n,{title:`生成大纲`,description:`免费生成，可继续编辑章节、小节、摘要`}),c(n,{title:`积分支付`,description:`确认订单并扣除积分`}),c(n,{title:`下载论文`,description:`生成完成后复制下载链接`})]),_:1})]),_:1})]),_:1}),c(m,{lg:16,xs:24},{default:i(()=>[c(p,{title:`文档中心`},{default:i(()=>[c(F,null,{default:i(()=>[c(E,{key:`workflow`,tab:`生成流程`},{default:i(()=>[c(w,null,{default:i(()=>[c(g,{level:4},{default:i(()=>[...t[0]||(t[0]=[h(`用户流程`,-1)])]),_:1}),c(S,null,{default:i(()=>[...t[1]||(t[1]=[h(` 输入论文题目，完善字数、参考文献、代码语言等配置后生成免费大纲。确认大纲后创建订单，使用积分支付并启动生成。 `,-1)])]),_:1}),c(g,{level:4},{default:i(()=>[...t[2]||(t[2]=[h(`积分规则`,-1)])]),_:1}),c(S,null,{default:i(()=>[...t[3]||(t[3]=[h(` 首版采用积分余额扣费。余额不足时不会扣费，订单不会进入生成中。生成失败后可联系管理员重试、人工补发下载链接或退回积分。 `,-1)])]),_:1})]),_:1})]),_:1}),c(E,{key:`token`,tab:`Token 接入`},{default:i(()=>[c(D,{class:`mb-4`,"show-icon":``,type:`warning`,message:`Token 只在生成或重置时展示明文`,description:`请不要把 Token 暴露在公开仓库、浏览器地址栏或前端静态代码里。`}),c(w,null,{default:i(()=>[c(S,null,{default:i(()=>[...t[4]||(t[4]=[h(` 调用 Token 用于外部系统访问论文生成接口。请在本页生成并妥善保存，页面常规展示只返回脱敏值。 `,-1)])]),_:1}),c(k,{class:`mb-4`,column:1,bordered:``,size:`small`},{default:i(()=>[c(O,{label:`当前 Token`},{default:i(()=>{var e;return[h(s(((e=v.value)==null?void 0:e.masked_token)||`未生成`),1)]}),_:1}),c(O,{label:`调用次数`},{default:i(()=>{var e,t;return[h(s((e=(t=v.value)==null?void 0:t.call_count)==null?0:e),1)]}),_:1}),c(O,{label:`创建时间`},{default:i(()=>{var e;return[h(s(((e=v.value)==null?void 0:e.created_at)||`-`),1)]}),_:1}),c(O,{label:`最近使用`},{default:i(()=>{var e;return[h(s(((e=v.value)==null?void 0:e.last_used_at)||`-`),1)]}),_:1})]),_:1}),y.value?(d(),o(D,{key:0,class:`mb-4`,"show-icon":``,type:`success`,message:`新 Token 仅本次展示，请复制后妥善保存`},{description:i(()=>[c(A,{copyable:``},{default:i(()=>[h(s(y.value),1)]),_:1})]),_:1})):f(``,!0),c(M,{class:`mb-4`},{default:i(()=>[c(j,{type:`primary`,loading:b.value,onClick:C},{default:i(()=>[...t[5]||(t[5]=[h(` 生成/重置 Token `,-1)])]),_:1},8,[`loading`]),c(j,{disabled:!y.value,onClick:T},{default:i(()=>[...t[6]||(t[6]=[h(` 复制明文 Token `,-1)])]),_:1},8,[`disabled`]),c(j,{loading:b.value,onClick:x},{default:i(()=>[...t[7]||(t[7]=[h(` 刷新状态 `,-1)])]),_:1},8,[`loading`])]),_:1}),c(S,null,{default:i(()=>[...t[8]||(t[8]=[h(`请求时使用 Bearer Token：`,-1)])]),_:1}),t[9]||(t[9]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`Authorization: Bearer YOUR_API_TOKEN`,-1))]),_:1})]),_:1}),c(E,{key:`developer`,tab:`开发对接教程`},{default:i(()=>[c(w,null,{default:i(()=>[c(g,{level:4},{default:i(()=>[...t[10]||(t[10]=[h(`1. 准备 Token`,-1)])]),_:1}),c(S,null,{default:i(()=>[...t[11]||(t[11]=[h(` 在“Token 接入”中生成调用 Token，服务端保存到环境变量或密钥管理系统，不要放进前端代码。 `,-1)])]),_:1}),t[21]||(t[21]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`AI_PAPER_TOKEN=YOUR_API_TOKEN
AI_PAPER_BASE_URL=https://your-domain.com/api/v1`,-1)),c(g,{level:4},{default:i(()=>[...t[12]||(t[12]=[h(`2. 生成大纲`,-1)])]),_:1}),t[22]||(t[22]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`POST /api/v1/thesis/outlines
Authorization: Bearer YOUR_API_TOKEN
Content-Type: application/json

{
  "title": "基于深度学习的图像识别技术研究",
  "form_params": {
    "lengthnum": 8000,
    "codetype": "Python",
    "language": "否",
    "wxnum": 25,
    "wxquote": "标注"
  },
  "about_msg": "侧重算法应用与实验分析",
  "three_level": false
}`,-1)),c(g,{level:4},{default:i(()=>[...t[13]||(t[13]=[h(`3. 创建并支付订单`,-1)])]),_:1}),c(S,null,{default:i(()=>[t[16]||(t[16]=h(` 使用大纲接口返回的 `,-1)),c(A,{code:``},{default:i(()=>[...t[14]||(t[14]=[h(`record_id`,-1)])]),_:1}),t[17]||(t[17]=h(` 和用户确认后的 `,-1)),c(A,{code:``},{default:i(()=>[...t[15]||(t[15]=[h(`outline`,-1)])]),_:1}),t[18]||(t[18]=h(` 创建订单，再调用积分支付接口启动生成任务。 `,-1))]),_:1}),t[23]||(t[23]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`POST /api/v1/thesis/orders
Authorization: Bearer YOUR_API_TOKEN

{
  "record_id": 123,
  "outline": [{ "chapter": "绪论", "sections": [{ "name": "研究背景", "abstract": "" }] }]
}

POST /api/v1/thesis/orders/pay
Authorization: Bearer YOUR_API_TOKEN

{ "order_sn": "AP202606030001" }`,-1)),c(g,{level:4},{default:i(()=>[...t[19]||(t[19]=[h(`4. 查询结果与下载`,-1)])]),_:1}),t[24]||(t[24]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`GET /api/v1/thesis/orders/status?order_sn=AP202606030001
Authorization: Bearer YOUR_API_TOKEN

GET /api/v1/thesis/orders/download-url?order_sn=AP202606030001
Authorization: Bearer YOUR_API_TOKEN`,-1)),c(g,{level:4},{default:i(()=>[...t[20]||(t[20]=[h(`5. Node.js 示例`,-1)])]),_:1}),t[25]||(t[25]=u(`pre`,{class:`rounded bg-muted p-3 text-xs`},`const baseUrl = process.env.AI_PAPER_BASE_URL;
const token = process.env.AI_PAPER_TOKEN;

async function request(path, options = {}) {
  const res = await fetch(\`\${baseUrl}\${path}\`, {
    ...options,
    headers: {
      Authorization: \`Bearer \${token}\`,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const json = await res.json();
  if (json.code !== 200) throw new Error(json.message || 'AI Paper API error');
  return json.data;
}`,-1))]),_:1})]),_:1}),c(E,{key:`api`,tab:`常用接口`},{default:i(()=>[c(k,{column:1,bordered:``,size:`small`},{default:i(()=>[c(O,{label:`生成大纲`},{default:i(()=>[c(A,{copyable:``},{default:i(()=>[...t[26]||(t[26]=[h(`/api/v1/thesis/outlines`,-1)])]),_:1})]),_:1}),c(O,{label:`创建订单`},{default:i(()=>[c(A,{copyable:``},{default:i(()=>[...t[27]||(t[27]=[h(`/api/v1/thesis/orders`,-1)])]),_:1})]),_:1}),c(O,{label:`积分支付`},{default:i(()=>[c(A,{copyable:``},{default:i(()=>[...t[28]||(t[28]=[h(`/api/v1/thesis/orders/pay`,-1)])]),_:1})]),_:1}),c(O,{label:`查询状态`},{default:i(()=>[c(A,{copyable:``},{default:i(()=>[...t[29]||(t[29]=[h(`/api/v1/thesis/orders/status`,-1)])]),_:1})]),_:1}),c(O,{label:`下载链接`},{default:i(()=>[c(A,{copyable:``},{default:i(()=>[...t[30]||(t[30]=[h(`/api/v1/thesis/orders/download-url`,-1)])]),_:1})]),_:1})]),_:1})]),_:1}),c(E,{key:`faq`,tab:`常见问题`},{default:i(()=>[c(P,null,{default:i(()=>[c(N,{key:`1`,header:`生成中可以离开页面吗？`},{default:i(()=>[...t[31]||(t[31]=[h(` 可以。论文生成任务在后端运行，回到“我的订单”打开详情即可继续查看状态。 `,-1)])]),_:1}),c(N,{key:`2`,header:`积分不足会扣费吗？`},{default:i(()=>[...t[32]||(t[32]=[h(` 不会。余额不足时支付接口会失败，订单不会进入生成中，也不会扣除积分。 `,-1)])]),_:1}),c(N,{key:`3`,header:`生成失败怎么办？`},{default:i(()=>[...t[33]||(t[33]=[h(` 可以把订单号发给管理员，由管理员查看失败原因并执行重试、补发链接或退积分。 `,-1)])]),_:1}),c(N,{key:`4`,header:`后台模型配置什么时候生效？`},{default:i(()=>[...t[34]||(t[34]=[h(` 管理员在“大模型配置”中启用对应用途的默认配置后，新提交的大纲、全文、摘要和参考文献关键词生成会优先使用后台配置；未配置时回退到服务端环境变量。 `,-1)])]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})]),_:1})}}});export{v as default};