import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {mergesAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {esc,formObject} from '../utils/html.js';
import {action,message} from '../hooks/action.js';

// 预览只保存在页面内存中；提交携带 verdict_key 保证重试沿用同一裁决。
let preview=null;
let selection={a_log:'',a_crash:0,b_log:'',b_crash:0,pinned:[]};

function sideOptions(side){
 return store.logs.map(l=>`<option value="${l.id}" ${String(selection[side+'_log'])===String(l.id)?'selected':''}>${esc(l.name)} · ${l.records.length}条</option>`).join('');
}
function currentLog(side){const id=Number(selection[side+'_log']);return store.logs.find(l=>l.id===id);}

export function mergePage(){
 if(!selection.a_log&&store.logs[0])selection.a_log=store.logs[0].id;
 if(!selection.b_log&&store.logs[1])selection.b_log=store.logs[1].id;
 const la=currentLog('a'),lb=currentLog('b');
 if(la&&selection.a_crash===0)selection.a_crash=la.records.length;
 if(lb&&selection.b_crash===0)selection.b_crash=lb.records.length;
 return `<div class="section-title"><h2>两班离线补录合账</h2><span>底账不同直接拒绝，仅收断电点前已提交整笔事务</span></div>
 <section class="split compact">
  <div><h2>第一步 · 选择两份日志和断电点</h2>
   <p>两份日志的初始账本必须完全一致。每份只取断电点（前N条已持久化）之前已经 commit 的整笔事务；未提交与已 abort 的事务整笔排除，并在预览中给出原因。</p>
   <p class="big-note">同班按原提交顺序，跨班同键才起冲突。</p>
  </div>
  <form id="merge-select">
   <label>A班日志集<select name="a_log">${sideOptions('a')}</select></label>
   <label>A班断电点（前N条已持久化）<input name="a_crash" type="number" min="0" max="${la?la.records.length:200}" value="${selection.a_crash}" required></label>
   <label>B班日志集<select name="b_log">${sideOptions('b')}</select></label>
   <label>B班断电点（前N条已持久化）<input name="b_crash" type="number" min="0" max="${lb?lb.records.length:200}" value="${selection.b_crash}" required></label>
   <button type="submit">生成合账预览 →</button>
  </form>
 </section>
 ${preview?previewSection(preview):'<p class="notice">选择两份日志与断电点后生成预览，合账前可逐项核对舍弃原因与冲突点。</p>'}
 <div class="section-title"><h2>历史合账记录</h2><span>新日志可再次进入故障注入与恢复演练</span></div>
 ${table(['编号','合账记录','状态','保留/舍弃','新日志集','证据'],store.merges.map(m=>{
   const s=m.verdict?.stats||{};
   return [m.id,esc(m.label),'<span class="badge completed">已合账</span>',
     `${s.kept??'—'} / ${s.committed??'—'} 笔保留`,
     esc(store.logs.find(l=>l.id===m.new_log_set_id)?.name||('#'+m.new_log_set_id)),
     `<a href="#mergeDetail/${m.id}">查看合账证据 →</a>`];
 }))}`;
}

function previewSection(v){
 const canWrite=session.role!=='viewer';
 const pinSet=new Set(selection.pinned);
 const conflictRefs=new Set((v.conflicts||[]).flatMap(c=>c.refs));
 return `<section class="preview-box">
  <div class="section-title"><h2>第二步 · 合账预览裁决</h2><span>模型 ${esc(v.model_version)}</span></div>
  <div class="verdict">
   <div><p>底账核对</p><h2>${v.initial_match?'底账一致，允许合账':'拒绝合账'}</h2></div>
   <p>已提交事务 ${v.stats.committed} 笔 · 保留 <b>${v.stats.kept}</b> 笔 · 冲突舍弃 ${v.stats.dropped_committed} 笔<br>
   断电前排除 ${v.stats.pre_crash_discarded} 笔 · 跨班冲突键 ${v.stats.conflict_keys} 个 · 新日志 ${v.stats.merged_records} 条<br>
   裁决键 <code>${esc(v.verdict_key.slice(0,16))}…</code>（重试提交沿用，不重复生成）</p>
  </div>
  <h2>跨班冲突点</h2>
  ${v.conflicts.length?table(['冲突键','涉及事务','各事务写入/提交LSN'],v.conflicts.map(c=>[
    esc(c.key),c.refs.map(r=>`<span class="chip ${pinSet.has(r)?'pinned':''}">${esc(r)}</span>`).join(' '),
    c.points.map(p=>`${esc(p.ref)}：写LSN ${p.write_lsn} / 提交LSN ${p.commit_lsn}`).join('<br>')])):
    '<p class="notice">两班没有写入同一个账本键，无跨班冲突。</p>'}
  <h2>已提交事务裁决（勾选 = 指定必须保住）</h2>
  <form id="pin-form">
   ${table(['保住','事务','班次','提交LSN','写入键','裁决','原因'],v.decisions.map(d=>[
     canWrite&&conflictRefs.has(d.ref)?`<input type="checkbox" name="pin" value="${esc(d.ref)}" ${pinSet.has(d.ref)?'checked':''}>`:'',
     esc(d.ref),d.side==='A'?'A班':'B班',d.commit_lsn,esc(d.keys.join('、')),
     d.kept?(pinSet.has(d.ref)?'<span class="badge completed pinned-badge">指定保留</span>':'<span class="badge completed">保留</span>'):'<span class="badge failed">舍弃</span>',
     esc(d.reason||'—')]))}
   ${canWrite?'<div class="toolbar"><button type="submit" class="secondary">按指定事务重新裁决</button></div>':''}
  </form>
  <h2>断电点前不合账的事务</h2>
  ${v.discarded.length?table(['事务','班次','舍弃原因'],v.discarded.map(d=>[esc(d.ref),d.side==='A'?'A班':'B班',esc(d.reason)])):
    '<p class="notice">无。</p>'}
  <h2>重放顺序与合账后账本</h2>
  <p>重放顺序（同班保持原提交顺序，A班先于B班）：${v.replay_order.map(r=>esc(r)).join(' → ')}</p>
  ${table(['账本键','底账值','合账后值'],Object.keys(v.merged_ledger).map(k=>[esc(k),v.initial[k],v.merged_ledger[k]]))}
  ${canWrite?`<form id="merge-commit" class="commit-form">
   <div class="fields">
    <label>合账记录名<input name="label" value="两班合账核对" required></label>
    <label>新日志集名称<input name="new_log_set_name" value="merged-${Date.now()}" required></label>
   </div>
   <label>说明<input name="description" value="两班离线补录合账生成，可再次演练"></label>
   <input type="hidden" name="verdict_key" value="${esc(v.verdict_key)}">
   <div class="toolbar"><button type="submit">第三步 · 确认合账并生成新日志</button><button type="button" class="secondary" id="retry-preview">重新拉取预览</button></div>
  </form>`:'<p class="readonly">观察员仅可预览与复核，合账需要操作员或管理员。</p>'}
 </section>`;
}

function requestBody(){
 return {side_a:{log_set_id:Number(selection.a_log),crash_after:Number(selection.a_crash)},
         side_b:{log_set_id:Number(selection.b_log),crash_after:Number(selection.b_crash)},
         pinned:[...selection.pinned]};
}

export function bindMerge(render){
 action(document.querySelector('#merge-select'),async f=>{
   const d=formObject(f);
   selection={a_log:Number(d.a_log),a_crash:Number(d.a_crash),b_log:Number(d.b_log),b_crash:Number(d.b_crash),pinned:[]};
   preview=await mergesAPI.preview(requestBody());
   message('预览已生成，请核对舍弃原因与冲突点');render();
 });
 action(document.querySelector('#pin-form'),async ()=>{
   selection.pinned=[...document.querySelectorAll('#pin-form input[name=pin]:checked')].map(x=>x.value);
   preview=await mergesAPI.preview(requestBody());
   message('已按指定事务重新裁决');render();
 });
 action(document.querySelector('#merge-commit'),async f=>{
   const d=formObject(f);
   const body={...requestBody(),verdict_key:d.verdict_key,label:d.label,new_log_set_name:d.new_log_set_name,description:d.description};
   const job=await mergesAPI.commit(body);
   preview=null;await render();location.hash='#mergeDetail/'+job.id;
 });
 document.querySelector('#retry-preview')?.addEventListener('click',async()=>{
   preview=await mergesAPI.preview(requestBody());message('预览已刷新');render();
 });
}
