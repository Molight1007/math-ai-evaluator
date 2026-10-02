#!/usr/bin/env bash
# =============================================================================
# monitor.sh — 评测期间的资源采样器（补 jsonl 里没有的数据）
# -----------------------------------------------------------------------------
# 为什么需要它
#   results/*.jsonl 每题都有 elapsed_sec / diag / verdicts，但**没有资源曲线**。
#   而「直编路径无全局锁，多线程可能同时起多个 Lean」这个 OOM 风险至今没有实测数据
#   （lean 单进程实测峰值：core 闭包 1134 MB / full 闭包 1851 MB，6 个叠加就压 8GB）。
#   本脚本把内存、swap、lean 进程数、负载、CPU 占用按固定间隔记成 CSV，
#   事后即可画曲线、定位峰值时刻，并与逐题耗时对齐。
#
# 用法
#   bash deploy/monitor.sh [输出CSV] [间隔秒] [总时长秒]
#   默认：logs/monitor_<时间戳>.csv  5 秒  0（=跑到没有 run_eval 进程为止）
#
# 输出列
#   ts,epoch,mem_total_mb,mem_avail_mb,mem_used_pct,swap_used_mb,swap_total_mb,
#   lean_procs,lean_rss_mb,python_procs,load1,cpu_pct,jsonl_lines
# =============================================================================
set -uo pipefail

OUT="${1:-logs/monitor_$(date +%m%d_%H%M%S).csv}"
INT="${2:-5}"
DUR="${3:-0}"

mkdir -p "$(dirname "$OUT")" 2>/dev/null || true

echo "ts,epoch,mem_total_mb,mem_avail_mb,mem_used_pct,swap_used_mb,swap_total_mb,lean_procs,lean_rss_mb,python_procs,load1,cpu_pct,jsonl_lines" > "$OUT"

# CPU 需要两次 /proc/stat 采样求差
read_cpu() { awk '/^cpu /{print $2+$3+$4+$6+$7+$8+$9, $5}' /proc/stat; }

prev="$(read_cpu)"
start=$(date +%s)
# ★ 防御：变量里若混入换行会把 CSV 一整行劈成多行（列错位、无法解析）。
#   实测踩到：`pgrep -c` 无匹配时**输出 0 且退出码为 1**，`|| echo 0` 于是又追加一个 0
#   ⇒ lean_n 变成 "0\n0" ⇒ 行被劈开。所以先剥掉所有内嵌换行，再补一个行尾换行。
log_line() {
    printf '%s' "$*" | tr -d '\r\n' >> "$OUT"
    printf '\n' >> "$OUT"
}
# 计数助手：只取 stdout，不因非零退出码重复输出
count_of() { local v; v="$("$@" 2>/dev/null)" || true; printf '%s' "${v:-0}" | tr -d '\n'; }

echo "[monitor] 输出 $OUT  间隔 ${INT}s  按 Ctrl-C 停止"

while :; do
    now=$(date +%s)
    ts=$(date '+%F %T')

    # 内存
    read -r mt ma < <(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{print t, a}' /proc/meminfo)
    read -r st su < <(awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{print t, t-f}' /proc/meminfo)
    mt_mb=$(( ${mt:-0} / 1024 )); ma_mb=$(( ${ma:-0} / 1024 ))
    st_mb=$(( ${st:-0} / 1024 )); su_mb=$(( ${su:-0} / 1024 ))
    if [ "$mt_mb" -gt 0 ]; then used_pct=$(( (mt_mb - ma_mb) * 100 / mt_mb )); else used_pct=0; fi

    # Lean / Python 进程
    # ⚠️ 必须用 count_of：`pgrep -c` 无匹配时输出 0 且退出码 1，
    #    写成 `$(pgrep -c ... || echo 0)` 会把 "0\n0" 塞进变量、劈开整行 CSV。
    lean_n=$(count_of pgrep -c -x lean)
    lean_rss=$(ps -C lean -o rss= 2>/dev/null | awk '{s+=$1} END{printf "%d", s/1024}')
    py_n=$(count_of pgrep -c -f 'run_eval|run_112')

    # 负载
    load1=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo 0)

    # CPU 占用（两次采样差）
    cur="$(read_cpu)"
    cpu_pct=$(awk -v p="$prev" -v c="$cur" 'BEGIN{
        split(p,P," "); split(c,C," ");
        dt=C[1]-P[1]; di=C[2]-P[2];
        if (dt+di<=0) {print 0} else {printf "%.1f", (dt/(dt+di))*100}
    }')
    prev="$cur"

    # 进度：**本次**会话结果的已完成题数（增量落盘，可反映推进）
    # ★ 2026-09-21 修复（原实现会给出**完全误导**的进度）：
    #   原：`jl=$(cat results/cloud*.jsonl 2>/dev/null | wc -l)` 有两处错——
    #   ① 硬编码 `cloud*` 前缀 ⇒ 当会话 tag 不是 cloud（如 `arm2`）时**恒不匹配**
    #      ⇒ 进度列永久停在历史值，完全不反映推进；
    #   ② 跨**全部** cloud*.jsonl **求和** ⇒ 把历史会话题数累加进来。
    #   实测：arm2 运行期间该列恒为 45（= 旧两轮 1 + 44）。
    #   现按**监视对象**推导：monitor CSV 名 `monitor_<tag>.csv` → 取最新
    #   `results/<tag>*.jsonl`；推导不出时回退到最新 jsonl（排除样例文件）。
    _tag=$(basename "${OUT:-}" 2>/dev/null | sed -n 's/^monitor_\(.*\)\.csv$/\1/p')
    _jf=""
    if [ -n "${_tag:-}" ]; then
        # 有 tag ⇒ 只认本会话文件；尚无匹配 ⇒ _jf 为空 ⇒ 下面 jl=0（正确）
        _jf=$(ls -t results/"$_tag"*.jsonl 2>/dev/null | grep -v '/deep_review_samples.jsonl' | head -1)
    else
        # ★ 仅当**推不出 tag**（异常用法）才回退最新 jsonl。
        #   推得出 tag 却无匹配 ⇒ 本会话还没落盘 ⇒ 进度应为 0；
        #   回退会读到上一轮文件、显示成一个**假的**进度（实测显示 44）。
        _jf=$(ls -t results/*.jsonl 2>/dev/null | grep -v '/deep_review_samples.jsonl' | head -1)
    fi
    if [ -n "${_jf:-}" ]; then
        jl=$(wc -l < "$_jf" 2>/dev/null | tr -d ' ')
        jl=${jl:-0}
    else
        jl=0
    fi

    log_line "$ts,$now,$mt_mb,$ma_mb,$used_pct,$su_mb,$st_mb,$lean_n,${lean_rss:-0},$py_n,$load1,$cpu_pct,$jl"

    # 停止条件
    if [ "$DUR" -gt 0 ] && [ $(( now - start )) -ge "$DUR" ]; then
        echo "[monitor] 已达指定时长 ${DUR}s，停止"
        break
    fi
    if [ "$DUR" -eq 0 ]; then
        # 没有任何 run_eval / run_112 进程了 → 评测已结束（连续 3 次确认，防抖动）
        if [ "$py_n" -eq 0 ]; then
            gone=$(( ${gone:-0} + 1 ))
            if [ "$gone" -ge 3 ]; then
                echo "[monitor] 评测进程已结束，停止"
                break
            fi
        else
            gone=0
        fi
    fi
    sleep "$INT"
done

echo "[monitor] 共 $(($(wc -l < "$OUT") - 1)) 行 → $OUT"
awk -F, 'NR>1{
    if($4+0<minav||NR==2) minav=$4;
    if($8+0>mxlean) mxlean=$8;
    if($9+0>mxrss) mxrss=$9;
    if($5+0>mxpct) mxpct=$5;
}
END{
    if(NR>1) printf "[monitor] 汇总：最低可用内存 %d MB / 最多 lean 进程 %d / lean 峰值RSS合计 %d MB / 内存占用峰值 %d%%\n",
        minav, mxlean, mxrss, mxpct;
}' "$OUT"
