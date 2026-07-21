"""
延迟分析脚本 — 读取 JMeter JTL 或 Python 压测 JSON，输出 P50/P90/P99 报告。

用法:
  # 分析 JMeter JTL 结果
  python tests/benchmark_report.py --jtl benchmark_results.jtl

  # 分析 Python benchmark_search.py 输出
  python tests/benchmark_report.py --json tests/_bench_results.json

  # 同时指定达标线
  python tests/benchmark_report.py --jtl results.jtl --threshold 500
"""
import argparse, csv, json, os, sys
from typing import Optional


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_vals):
        return sorted_vals[f] + c * (sorted_vals[f + 1] - sorted_vals[f])
    return sorted_vals[f]


def analyze_jtl(filepath: str, threshold_ms: float = 500) -> dict:
    """分析 JMeter JTL 结果文件。"""
    latencies: list[float] = []
    errors = 0
    labels: dict[str, list[float]] = {}

    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                label = row.get("label", "unknown")
                elapsed = float(row.get("elapsed", 0))
                success = row.get("success", "true").lower() == "true"

                if success and elapsed > 0:
                    latencies.append(elapsed)
                    labels.setdefault(label, []).append(elapsed)
                else:
                    errors += 1
            except (ValueError, KeyError):
                errors += 1

    return _build_report(latencies, errors, labels, threshold_ms, "JMeter JTL", filepath)


def _build_report(
    latencies: list[float],
    errors: int,
    labels: dict[str, list[float]],
    threshold_ms: float,
    source: str,
    filepath: str,
) -> dict:
    s = sorted(latencies)
    total = len(s) + errors
    report = {
        "source": source,
        "file": filepath,
        "total_requests": total,
        "errors": errors,
        "error_rate": round(errors / max(total, 1) * 100, 2),
        "latency": {
            "p50": round(percentile(s, 50), 1),
            "p90": round(percentile(s, 90), 1),
            "p95": round(percentile(s, 95), 1),
            "p99": round(percentile(s, 99), 1),
            "avg": round(sum(s) / max(len(s), 1), 1),
            "min": round(s[0], 1) if s else 0,
            "max": round(s[-1], 1) if s else 0,
        },
        "threshold": {
            "target_ms": threshold_ms,
            "p90": round(percentile(s, 90), 1),
            "pass": percentile(s, 90) <= threshold_ms,
        },
    }

    # 按标签分组
    if len(labels) > 1:
        report["by_label"] = {}
        for label, vals in sorted(labels.items()):
            sv = sorted(vals)
            report["by_label"][label] = {
                "count": len(vals),
                "p50": round(percentile(sv, 50), 1),
                "p90": round(percentile(sv, 90), 1),
                "p99": round(percentile(sv, 99), 1),
                "avg": round(sum(sv) / len(sv), 1),
            }

    return report


def analyze_json(filepath: str, threshold_ms: float = 500) -> list[dict]:
    """分析 Python benchmark_search.py 输出的 JSON。"""
    with open(filepath, encoding='utf-8') as f:
        data = json.load(f)

    results = data.get("results", [data])
    reports = []
    for r in results:
        latencies = []
        # 从 raw_latencies 或 summary stats 重建（此处用已计算的统计值）
        reports.append({
            "concurrency": r.get("concurrency", "?"),
            "total_requests": r.get("total_requests", 0),
            "errors": r.get("errors", 0),
            "p50": r.get("p50", 0),
            "p90": r.get("p90", 0),
            "p95": r.get("p95", 0),
            "p99": r.get("p99", 0),
            "avg": r.get("avg", 0),
            "qps": r.get("qps", 0),
            "p90_pass": r.get("p90", 999) <= threshold_ms,
        })
    return reports


def print_report(report: dict | list, threshold_ms: float):
    """格式化打印报告。"""
    print(f"\n{'='*70}")
    print(f"记忆检索延迟分析报告")
    print(f"{'='*70}")

    if isinstance(report, list):
        # 多轮结果
        print(f"{'并发':>6} | {'请求':>7} | {'P50':>8} | {'P90':>8} | {'P99':>8} | {'avg':>8} | {'QPS':>8} | {'P90≤' + str(threshold_ms) + 'ms':>10}")
        print(f"{'─'*6}─┼─{'─'*7}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*8}─┼─{'─'*10}")
        for r in report:
            status = "✅" if r.get("p90_pass") else "❌"
            print(f"{r['concurrency']:>6} | {r['total_requests']:>7} | "
                  f"{r['p50']:>7}ms | {r['p90']:>7}ms | {r['p99']:>7}ms | "
                  f"{r['avg']:>7}ms | {r['qps']:>7.1f} | {status:>10}")
    else:
        # 单轮 JMeter 结果
        r = report
        print(f"来源: {r['source']}")
        print(f"文件: {r['file']}")
        print(f"请求: {r['total_requests']}  |  错误: {r['errors']} ({r['error_rate']}%)")
        print(f"\n{'─'*40}")
        l = r["latency"]
        print(f"  P50:  {l['p50']}ms")
        print(f"  P90:  {l['p90']}ms")
        print(f"  P95:  {l['p95']}ms")
        print(f"  P99:  {l['p99']}ms")
        print(f"  avg:  {l['avg']}ms")
        print(f"  min:  {l['min']}ms")
        print(f"  max:  {l['max']}ms")
        print(f"\n  P90 ≤ {r['threshold']['target_ms']}ms: {'✅ PASS' if r['threshold']['pass'] else '❌ FAIL'}")

        if "by_label" in r:
            print(f"\n{'─'*40}")
            print("按线程组分组:")
            print(f"{'线程组':<20} | {'数量':>6} | {'P50':>8} | {'P90':>8} | {'P99':>8}")
            for label, stats in r["by_label"].items():
                print(f"{label:<20} | {stats['count']:>6} | "
                      f"{stats['p50']:>7}ms | {stats['p90']:>7}ms | {stats['p99']:>7}ms")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="延迟分析报告")
    parser.add_argument("--jtl", help="JMeter JTL 结果文件路径")
    parser.add_argument("--json", help="Python benchmark JSON 文件路径")
    parser.add_argument("--threshold", type=float, default=500, help="P90 达标线(ms)")
    args = parser.parse_args()

    if args.jtl:
        if not os.path.exists(args.jtl):
            print(f"❌ 文件不存在: {args.jtl}")
            sys.exit(1)
        report = analyze_jtl(args.jtl, args.threshold)
        print_report(report, args.threshold)

    elif args.json:
        if not os.path.exists(args.json):
            print(f"❌ 文件不存在: {args.json}")
            sys.exit(1)
        report = analyze_json(args.json, args.threshold)
        print_report(report, args.threshold)

    else:
        print("请指定 --jtl 或 --json 文件")
        print("示例: python tests/benchmark_report.py --jtl benchmark_results.jtl")
        print("示例: python tests/benchmark_report.py --json tests/_bench_results.json")
