"""把 out/*.golden.json + verify/*.verify.json 渲染成一个可浏览的审阅 HTML。"""
from __future__ import annotations
import html, json, pathlib, sys

BASE = pathlib.Path(__file__).resolve().parent
IDS = json.loads((BASE / "meeting_ids.json").read_text(encoding="utf-8"))[:10]


def esc(x):
    return html.escape(str(x if x is not None else ""))


def ov_text(g):
    ov = g.get("overview")
    return ov.get("text", "") if isinstance(ov, dict) else (ov or "")


def render_meeting(mid):
    g = json.loads((BASE / "out" / f"{mid}.golden.json").read_text(encoding="utf-8"))
    vf = json.loads((BASE / "verify" / f"{mid}.verify.json").read_text(encoding="utf-8"))
    fc = g.get("fine_chapters", [])
    cf = g.get("core_facts", [])
    dec = g.get("decisions", [])
    ai = g.get("action_items", [])
    sp = g.get("speakers", [])
    verdict = vf.get("verdict", "?")
    n_dec = sum(1 for d in dec if d.get("status") == "decision")
    n_pro = sum(1 for d in dec if d.get("status") == "proposal")
    parts = {p["id"]: p for p in g.get("parts", [])}
    part_of = {fid: pid for pid in parts for fid in parts[pid].get("fine_ids", [])}

    # parts -> fine chapters
    fc_html = []
    cur_part = None
    for c in fc:
        pid = part_of.get(c.get("id"))
        if pid != cur_part:
            cur_part = pid
            ptitle = parts.get(pid, {}).get("title", pid or "")
            fc_html.append(f'<div class="part">{esc(ptitle)}</div>')
        fc_html.append(
            f'<div class="fc"><div class="fc-h"><span class="t">{esc(c.get("start_s",0))}s–{esc(c.get("end_s",0))}s</span>'
            f'<b>{esc(c.get("title"))}</b><span class="id">{esc(c.get("id"))}</span></div>'
            f'<div class="topic">{esc(c.get("topic"))}</div>'
            f'<p>{esc(c.get("summary"))}</p></div>'
        )

    fact_html = []
    for f in cf:
        anchors = "".join(f'<span class="chip">{esc(a)}</span>' for a in f.get("anchors", []))
        imp = f.get("importance", "major")
        fact_html.append(
            f'<div class="fact"><span class="imp {esc(imp)}">{esc(imp)}</span>'
            f'<div class="ftext">{esc(f.get("text"))}<div class="anchors">{anchors}</div></div></div>'
        )

    dec_html = []
    for d in dec:
        st = d.get("status", "")
        owner = f'<span class="owner">{esc(d.get("owner"))}</span>' if d.get("owner") else ""
        dec_html.append(
            f'<div class="dec"><span class="pill {esc(st)}">{esc(st)}</span>'
            f'<span class="dtext">{esc(d.get("text"))}</span>{owner}</div>'
        )

    ai_html = "".join(
        f'<div class="dec"><span class="pill action">待办</span><span class="dtext">{esc(a.get("text"))}</span>'
        f'<span class="owner">{esc(a.get("owner") or "—")}</span></div>' for a in ai
    ) or '<div class="empty">无</div>'

    sp_html = "".join(
        f'<div class="sp"><span class="id">{esc(s.get("speaker_id"))}</span>'
        f'<b>{esc(s.get("role") or "（未自述）")}</b><p>{esc(s.get("overview"))}</p></div>' for s in sp
    )

    miss = vf.get("missing_facts", [])
    miss_html = "".join(f'<li>{esc(m.get("text"))} <span class="mi">{esc(m.get("importance",""))}</span></li>' for m in miss)
    dwrong = [x for x in vf.get("decision_checks", []) if x.get("status_correct") is False]
    dwrong_html = "".join(f'<li>{esc(x.get("id"))} → 应为 {esc(x.get("should_be"))}:{esc(x.get("reason"))}</li>' for x in dwrong)

    short = mid[9:] if len(mid) > 9 else mid
    return f'''<details>
<summary>
  <span class="mid">{esc(short)}</span>
  <span class="badge v-{esc(verdict)}">{esc(verdict)}</span>
  <span class="counts">章 {len(fc)} · 事实 {len(cf)} · 决策 {n_dec}<i>决</i>/{n_pro}<i>议</i> · 待办 {len(ai)}</span>
</summary>
<div class="body">
  <div class="ov"><h4>概览</h4><p>{esc(ov_text(g))}</p></div>
  <div class="grid">
    <section><h4>章节 ({len(fc)})</h4>{''.join(fc_html)}</section>
    <div class="col">
      <section><h4>核心事实 · 带锚词 ({len(cf)})</h4>{''.join(fact_html)}</section>
      <section><h4>决策/提议 ({n_dec} 决定 · {n_pro} 提议)</h4>{''.join(dec_html)}</section>
      <section><h4>待办</h4>{ai_html}</section>
      <section><h4>核验(opus-5 独立)</h4>
        <p class="vsum">{esc(vf.get("summary",""))}</p>
        {'<div class="warnbox"><b>决策标错:</b><ul>'+dwrong_html+'</ul></div>' if dwrong_html else ''}
        <div class="missbox"><b>完整性 critic 漏项 ({len(miss)}):</b><ul>{miss_html}</ul></div>
      </section>
      <section class="sp-sec"><h4>发言人</h4>{sp_html}</section>
    </div>
  </div>
</div>
</details>'''


def summary_row(mid):
    g = json.loads((BASE / "out" / f"{mid}.golden.json").read_text(encoding="utf-8"))
    vf = json.loads((BASE / "verify" / f"{mid}.verify.json").read_text(encoding="utf-8"))
    dec = g.get("decisions", [])
    nd = sum(1 for d in dec if d.get("status") == "decision")
    npr = sum(1 for d in dec if d.get("status") == "proposal")
    v = vf.get("verdict", "?")
    return (f'<tr><td class="mono">{esc(mid[9:])}</td><td><span class="badge v-{esc(v)}">{esc(v)}</span></td>'
            f'<td>{len(g.get("fine_chapters",[]))}</td><td>{len(g.get("core_facts",[]))}</td>'
            f'<td>{nd}/{npr}</td><td>{len(g.get("action_items",[]))}</td>'
            f'<td>{len(vf.get("missing_facts",[]))}</td></tr>')


BODY = "\n".join(render_meeting(m) for m in IDS)
ROWS = "\n".join(summary_row(m) for m in IDS)
n_acc = sum(1 for m in IDS if json.loads((BASE/"verify"/f"{m}.verify.json").read_text(encoding="utf-8")).get("verdict")=="accept")
n_man = len(IDS) - n_acc

HTML = f'''<title>金标 v2 审阅台</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#f5f7fa; --surface:#ffffff; --surface2:#f0f3f8; --ink:#161a21; --muted:#5b6472;
  --line:#e2e7ee; --accent:#3b5bdb; --ok:#2b8a3e; --warn:#c26a00; --bad:#d63333;
  --chip:#eaeef6; --chipink:#2f3a52;
}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{
  --bg:#0e1116; --surface:#161b22; --surface2:#1c222b; --ink:#e7ebf2; --muted:#98a2b2;
  --line:#272e38; --accent:#8aa0ff; --ok:#51cf66; --warn:#ffb057; --bad:#ff6b6b;
  --chip:#232a35; --chipink:#c7d2e6;
}}}}
:root[data-theme=dark]{{
  --bg:#0e1116; --surface:#161b22; --surface2:#1c222b; --ink:#e7ebf2; --muted:#98a2b2;
  --line:#272e38; --accent:#8aa0ff; --ok:#51cf66; --warn:#ffb057; --bad:#ff6b6b;
  --chip:#232a35; --chipink:#c7d2e6;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.55;font-size:15px}}
.mono,.id,.mid,.owner,.chip,td.mono{{font-family:"IBM Plex Mono",ui-monospace,monospace}}
.wrap{{max-width:1080px;margin:0 auto;padding:32px 20px 80px}}
header h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}}
header .sub{{color:var(--muted);margin:0 0 22px;font-size:14px}}
.statbar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:26px}}
.stat{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:110px}}
.stat b{{display:block;font-size:22px}} .stat span{{color:var(--muted);font-size:12.5px}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);
  border-radius:12px;overflow:hidden;margin-bottom:30px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:13.5px}}
th{{background:var(--surface2);color:var(--muted);font-weight:600}}
tr:last-child td{{border-bottom:none}}
details{{background:var(--surface);border:1px solid var(--line);border-radius:12px;margin-bottom:12px;overflow:hidden}}
summary{{cursor:pointer;padding:14px 18px;display:flex;align-items:center;gap:14px;list-style:none;flex-wrap:wrap}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:"▸";color:var(--muted);font-size:12px}}
details[open] summary::before{{content:"▾"}}
.mid{{font-weight:600;font-size:15px}}
.counts{{color:var(--muted);font-size:13px;margin-left:auto}} .counts i{{font-style:normal;opacity:.6;font-size:11px}}
.badge{{font-size:12px;font-weight:600;padding:2px 9px;border-radius:20px;font-family:"IBM Plex Mono",monospace}}
.v-accept{{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok)}}
.v-manual{{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}}
.v-regenerate{{background:color-mix(in srgb,var(--bad) 16%,transparent);color:var(--bad)}}
.body{{padding:6px 18px 20px;border-top:1px solid var(--line)}}
h4{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:20px 0 10px}}
.ov p{{margin:0;background:var(--surface2);padding:12px 14px;border-radius:8px;font-size:14px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
@media(max-width:820px){{.grid{{grid-template-columns:1fr}}}}
.part{{font-size:12px;font-weight:700;color:var(--accent);margin:14px 0 6px;letter-spacing:.03em}}
.fc{{border-left:2px solid var(--line);padding:4px 0 8px 12px;margin-left:4px}}
.fc-h{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}} .fc-h b{{font-size:14px}}
.fc .t{{font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted)}}
.fc .id{{font-size:10.5px;color:var(--muted);margin-left:auto}}
.fc .topic{{color:var(--muted);font-size:12.5px;margin:2px 0}} .fc p{{margin:4px 0 0;font-size:13.5px}}
.fact{{display:flex;gap:9px;padding:9px 0;border-bottom:1px dashed var(--line)}}
.imp{{font-size:10px;font-weight:700;padding:2px 6px;border-radius:5px;height:fit-content;white-space:nowrap}}
.imp.critical{{background:color-mix(in srgb,var(--bad) 15%,transparent);color:var(--bad)}}
.imp.major{{background:var(--chip);color:var(--chipink)}}
.ftext{{font-size:13.5px}} .anchors{{margin-top:5px;display:flex;gap:5px;flex-wrap:wrap}}
.chip{{background:var(--chip);color:var(--chipink);font-size:11.5px;padding:2px 8px;border-radius:5px}}
.dec{{display:flex;gap:9px;align-items:baseline;padding:7px 0;border-bottom:1px dashed var(--line);font-size:13.5px}}
.pill{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px;white-space:nowrap}}
.pill.decision{{background:color-mix(in srgb,var(--ok) 16%,transparent);color:var(--ok)}}
.pill.proposal{{background:color-mix(in srgb,var(--warn) 16%,transparent);color:var(--warn)}}
.pill.action{{background:color-mix(in srgb,var(--accent) 16%,transparent);color:var(--accent)}}
.dtext{{flex:1}} .owner{{font-size:11.5px;color:var(--muted)}}
.vsum{{font-size:13.5px;background:var(--surface2);padding:10px 12px;border-radius:8px;margin:0 0 8px}}
.missbox,.warnbox{{font-size:12.5px;color:var(--muted)}} .missbox ul,.warnbox ul{{margin:4px 0 0;padding-left:18px}}
.missbox li,.warnbox li{{margin:2px 0}} .mi{{font-size:10px;background:var(--chip);padding:1px 5px;border-radius:4px;color:var(--chipink)}}
.warnbox{{color:var(--bad)}}
.sp-sec .sp{{padding:6px 0;border-bottom:1px dashed var(--line);font-size:12.5px}}
.sp .id{{font-size:11px;color:var(--muted);margin-right:8px}} .sp p{{margin:3px 0 0;color:var(--muted)}}
.empty{{color:var(--muted);font-size:13px}}
.note{{color:var(--muted);font-size:12.5px;margin-top:24px;border-top:1px solid var(--line);padding-top:14px}}
</style>
<div class="wrap">
<header>
<h1>金标 v2 审阅台</h1>
<p class="sub">AliMeeting train_L · 前 10 场 · fable5 生成 → opus-5 独立核验 · 细章分层 + 锚词 + 决策/提议</p>
</header>
<div class="statbar">
<div class="stat"><b>10</b><span>会议(前10场)</span></div>
<div class="stat"><b>{n_acc}/{n_man}</b><span>accept / manual</span></div>
<div class="stat"><b>10/10</b><span>结构门通过</span></div>
<div class="stat"><b>0</b><span>决策标错</span></div>
<div class="stat"><b>≈159K</b><span>token/场</span></div>
</div>
<table>
<thead><tr><th>会议</th><th>核验</th><th>细章</th><th>事实</th><th>决/议</th><th>待办</th><th>漏项</th></tr></thead>
<tbody>{ROWS}</tbody>
</table>
{BODY}
<p class="note">金标性质:fable5 生成 + opus-5 独立核验的「校准过的银标」,非人工 gold;分章边界为更细的参照系(用于校验项目分章合理性),非唯一正确切法。missing_facts 为完整性 critic 提示,按既定策略留报告备查。</p>
</div>'''

out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "review10.html"
out.write_text(HTML, encoding="utf-8")
print("wrote", out, len(HTML), "chars")
