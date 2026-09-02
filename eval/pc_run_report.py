import sys,os,shutil,pathlib,json
sys.path.insert(0,r'C:\Users\Admin\meet\src')
from meeting_agent.observability.run_report import build_run_report
SP=os.path.dirname(os.path.abspath(__file__))
srcdir=pathlib.Path(SP)/'pc_summary_out'
# 摆成 build_run_report 期望的布局: root/03_llm_summary/
root=pathlib.Path(SP)/'pc_report_root'
llm=root/'03_llm_summary'
if root.exists(): shutil.rmtree(root)
llm.parent.mkdir(parents=True,exist_ok=True)
shutil.copytree(srcdir,llm)
# 补 root 下的 meeting_result(含stage耗时,若无则最小占位)
# 从之前跑的日志估个耗时占位(PC真跑时应由pipeline写)
(root/'run_metrics.json').write_text(json.dumps({"stage_elapsed_seconds":{"llm_summary":"见实测"}},ensure_ascii=False),encoding='utf-8')
report=build_run_report(root)
# 输出
out=pathlib.Path(SP)/'pc_run_report.json'
json.dump(report,open(out,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
print('=== PC run_report 关键部分 ===')
print('红旗:',report.get('flags') or report.get('optimization_flags') or '(看下面)')
for k in ['segmentation','block_summary','llm_economics','flags']:
    if k in report: print(f'\n[{k}]',json.dumps(report[k],ensure_ascii=False)[:400])
print('\n全部顶层键:',list(report.keys()))
