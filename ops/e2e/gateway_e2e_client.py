#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前端→板端→回前端 端到端客户端(仅标准库)。

复刻浏览器 UI(meeting_agent_gateway_ui_v0.html)对本地 Gateway 的调用序列,
把"前端提交 → Gateway 转板端 Board Agent → 板端 Harness 6 阶段 → 结果回投前端"
这条完整链路在无人值守下真跑一遍并打印证据。

调用序列(全部打到 Gateway HTTP API,与浏览器完全一致):
  1. GET  /api/info                      —— 前端发现 Gateway
  2. GET  /api/board/health              —— Gateway 代理板端健康
  3. POST /api/meetings                  —— 建会(task_kind=harness_meeting_v0),拿 meeting_id/board_task_id
  4. PUT  /api/meetings/{id}/audio       —— 上传本地 WAV(Gateway 转板端 /v1/tasks/{tid}/audio,板端后台起 Harness)
  5. GET  /api/meetings/{id}  轮询        —— 直到板端任务终态
  6. GET  /api/meetings/{id}/result      —— 拉回投影结果(纪要/发言人/待办/enrichment)

用法(实验机):
  python ops/e2e/gateway_e2e_client.py --gateway http://127.0.0.1:8787 \
      --audio "D:/Meeting_Agent_mainline/runtime/meeting_library_agent1/meetings/<mid>/source.wav"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

TERMINAL = {"completed", "succeeded", "failed", "cancelled", "error"}


def _req(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001
        return -1, repr(exc).encode()


def _json(method, url, obj=None, timeout=120):
    data = None
    headers = {"Accept": "application/json"}
    if obj is not None:
        data = json.dumps(obj).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, body = _req(method, url, data=data, headers=headers, timeout=timeout)
    try:
        parsed = json.loads(body.decode("utf-8", "replace")) if body else {}
    except Exception:  # noqa: BLE001
        parsed = {"_raw": body.decode("utf-8", "replace")[:800]}
    return status, parsed


def _state_of(task):
    if not isinstance(task, dict):
        return "?"
    bt = task.get("board_task") if isinstance(task.get("board_task"), dict) else task
    return str(bt.get("state") or bt.get("status") or "?")


def _stage_of(task):
    bt = task.get("board_task") if isinstance(task.get("board_task"), dict) else task
    return str(bt.get("stage") or bt.get("current_stage") or "-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:8787")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--meeting-id", default=None, help="复用已建会议(跳过建会),用于恢复中断的运行")
    ap.add_argument("--poll-interval", type=float, default=10.0)
    ap.add_argument("--timeout", type=float, default=1500.0)
    args = ap.parse_args()
    gw = args.gateway.rstrip("/")

    def log(*a):
        print(*a, flush=True)

    t0 = time.time()
    log("========== 端到端 前端→板端→回前端 ==========")
    log("gateway :", gw)
    log("audio   :", args.audio)

    # 1. 前端发现 Gateway
    s, info = _json("GET", f"{gw}/api/info", timeout=15)
    log(f"\n[1] GET /api/info -> {s}  service={info.get('service')} board_url={info.get('board_url')}")
    if s != 200:
        log("!! Gateway 未就绪,终止"); return 2

    # 2. Gateway 代理板端健康
    s, health = _json("GET", f"{gw}/api/board/health", timeout=20)
    log(f"[2] GET /api/board/health -> {s}  status={health.get('status')} busy={health.get('busy')} profile={health.get('model_profile')}")
    if s != 200 or health.get("status") != "ready":
        log("!! 板端不健康,终止"); return 3

    # 3. 建会(或复用已有会议)
    if args.meeting_id:
        mid = args.meeting_id
        log(f"[3] 复用已建会议 meeting_id={mid}(跳过建会)")
    else:
        s, created = _json("POST", f"{gw}/api/meetings", {"task_kind": "harness_meeting_v0"}, timeout=60)
        log(f"[3] POST /api/meetings -> {s}")
        if s not in (200, 201, 202):
            log("!! 建会失败:", json.dumps(created, ensure_ascii=False)[:600]); return 4
        mid = created.get("meeting_id")
        btid = created.get("board_task_id")
        log(f"    meeting_id={mid}  board_task_id={btid}  state={_state_of(created)}")

    # 4. 上传音频(Gateway 转板端,板端起 Harness)
    with open(args.audio, "rb") as fh:
        blob = fh.read()
    sha = hashlib.sha256(blob).hexdigest()
    log(f"[4] PUT /api/meetings/{mid}/audio  bytes={len(blob)} sha256={sha[:16]}...")
    up_headers = {"Content-Type": "audio/wav", "Content-Length": str(len(blob)), "X-File-SHA256": sha}
    s, up = _req("PUT", f"{gw}/api/meetings/{mid}/audio", data=blob, headers=up_headers, timeout=300)
    try:
        up_obj = json.loads(up.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        up_obj = {"_raw": up.decode("utf-8", "replace")[:600]}
    log(f"    -> {s}  state={_state_of(up_obj)} stage={_stage_of(up_obj)}")
    if s >= 300:
        log("!! 上传失败:", json.dumps(up_obj, ensure_ascii=False)[:600]); return 5

    # 5. 轮询到终态
    log(f"[5] 轮询 GET /api/meetings/{mid} (每 {args.poll_interval:.0f}s)")
    last = None
    state = _state_of(up_obj)
    while time.time() - t0 < args.timeout:
        time.sleep(args.poll_interval)
        s, task = _json("GET", f"{gw}/api/meetings/{mid}", timeout=30)
        if s != 200:
            log(f"    poll -> {s} {json.dumps(task, ensure_ascii=False)[:300]}"); continue
        state = _state_of(task); stage = _stage_of(task)
        el = time.time() - t0
        line = f"    t+{el:6.0f}s  state={state}  stage={stage}"
        if line != last:
            log(line); last = line
        if state in TERMINAL:
            break

    el = time.time() - t0
    log(f"\n[5] 终态 state={state}  用时 {el:.0f}s")
    if state not in ("completed", "succeeded"):
        log("!! 未成功完成");
        s, task = _json("GET", f"{gw}/api/meetings/{mid}", timeout=30)
        log("    末次任务:", json.dumps(task, ensure_ascii=False)[:1200])
        return 6

    # 6. 拉结果(回前端)
    s, result = _json("GET", f"{gw}/api/meetings/{mid}/result", timeout=120)
    log(f"[6] GET /api/meetings/{mid}/result -> {s}")
    if s != 200:
        log("!! 拉结果失败:", json.dumps(result, ensure_ascii=False)[:600]); return 7

    # 结果摘要(不打印全文,避免刷屏)。注意:投影结果嵌在 result["result"] 下,
    # 顶层键通常是 task_id/meeting_id/result/artifact_refs。
    def dig(d, *ks):
        for k in ks:
            d = d.get(k) if isinstance(d, dict) else None
        return d
    log("result 顶层键:", ",".join(list(result.keys())[:20]))
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    # 纪要主体可能在 payload / payload["summary"] / payload["meeting_summary"] 下,逐个兜底
    body = None
    for cand in (payload.get("summary"), payload.get("meeting_summary"), payload):
        if isinstance(cand, dict) and (cand.get("title") or cand.get("overview") or cand.get("chapters")):
            body = cand; break
    body = body or payload
    title = body.get("title") if isinstance(body, dict) else None
    overview = body.get("overview") if isinstance(body, dict) else None
    chapters = (body.get("chapters") if isinstance(body, dict) else None) or []
    speakers = (body.get("speakers") if isinstance(body, dict) else None) or []
    actions = (body.get("action_items") if isinstance(body, dict) else None) or []
    enrich = payload.get("enrichment") if isinstance(payload.get("enrichment"), dict) else {}
    arefs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}
    log("---------- 结果投影(回前端) ----------")
    log("title    :", (title or "")[:120])
    log("overview :", (overview or "")[:240])
    log(f"chapters ={len(chapters)}  speakers={len(speakers)}  action_items={len(actions)}")
    if enrich:
        log("enrichment keys:", ",".join(list(enrich.keys())[:12]))
    if arefs:
        log("artifact_refs:", ",".join(list(arefs.keys())[:20]))
    log(f"\n[OK] 端到端成功: 前端(Gateway API) -> 板端 Harness 6 阶段 -> 结果回投, 用时 {el:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
