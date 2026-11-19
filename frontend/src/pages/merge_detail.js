import {table} from '../components/common/table.js';
import {esc} from '../utils/html.js';
import {downloadMerge} from '../api/client.js';
import {message} from '../hooks/action.js';

export function mergeDetailPage(job){
 if(!job)return '<section class="empty"><h2>还没有合账记录</h2><p>先在两班合账演练中选择两份日志并确认裁决。</p><a href="#merge">进入合账演练 →</a></section>';
 const v=job.verdict;
 return `<div class="section-title"><h2>${esc(job.label)} <small>#${job.id}</small></h2><span class="badge completed">已合账</span></div>
 <section class="verdict">
  <div><p>合账裁决核对</p><h2>${v.stats.kept} / ${v.stats.committed} 笔已提交事务保留</h2></div>
  <p>模型 ${esc(v.model_version)}<br>
  A班：${esc(v.sides[0].name)} · 断电点 ${v.sides[0].crash_after}<br>
  B班：${esc(v.sides[1].name)} · 断电点 ${v.sides[1].crash_after}<br>
  指定保留：${esc((v.pinned||[]).join('、')||'无')} · 新日志集 #${job.new_log_set_id}（原日志保持不变）</p>
 </section>
 <h2>跨班冲突点</h2>
 ${v.conflicts.length?table(['冲突键','涉及事务','各事务写入/提交LSN'],v.conflicts.map(c=>[
   esc(c.key),c.refs.map(r=>`<span class="chip">${esc(r)}</span>`).join(' '),
   c.points.map(p=>`${esc(p.ref)}：写LSN ${p.write_lsn} / 提交LSN ${p.commit_lsn}`).join('<br>')])):
   '<p class="notice">无跨班冲突。</p>'}
 <h2>事务裁决与舍弃原因</h2>
 ${table(['事务','班次','提交LSN','写入键','裁决','原因'],v.decisions.map(d=>[
   esc(d.ref),d.side==='A'?'A班':'B班',d.commit_lsn,esc(d.keys.join('、')),
   d.kept?'<span class="badge completed">保留</span>':'<span class="badge failed">舍弃</span>',
   esc(d.reason||'—')]))}
 <h2>断电点前不合账事务</h2>
 ${v.discarded.length?table(['事务','班次','舍弃原因'],v.discarded.map(d=>[esc(d.ref),d.side==='A'?'A班':'B班',esc(d.reason)])):'<p class="notice">无。</p>'}
 <h2>合账后账本与重放顺序</h2>
 <p>重放顺序：${v.replay_order.map(r=>esc(r)).join(' → ')}（同班原提交顺序，A班先于B班）</p>
 ${table(['账本键','底账值','合账后值'],Object.keys(v.merged_ledger).map(k=>[esc(k),v.initial[k],v.merged_ledger[k]]))}
 <div class="toolbar">
  <button id="export-merge">导出合账裁决证据</button>
  <a class="button-link" href="#cases">用新日志去设置断电点 →</a>
  <a class="button-link secondary-link" href="#runs">对新日志发起恢复演练 →</a>
 </div>
 <p class="checksum">输入摘要 ${esc(v.input_sha256)}<br>结果摘要 ${esc(v.result_sha256)}<br>裁决键（重试幂等）${esc(v.verdict_key)}</p>
 <details><summary>查看生成的新日志（可再次演练，原日志未改动）</summary><pre>${esc(JSON.stringify(v.merged_records,null,2))}</pre></details>
 <details><summary>查看冻结输入快照</summary><pre>${esc(JSON.stringify(job.snapshot,null,2))}</pre></details>`;
}

export function bindMergeDetail(job,render){
 document.querySelector('#export-merge')?.addEventListener('click',()=>downloadMerge(job.id).catch(e=>message(e.message,true)));
}
