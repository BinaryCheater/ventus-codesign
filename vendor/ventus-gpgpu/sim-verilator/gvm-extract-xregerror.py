#!/usr/bin/env python3
"""
extract_gvm_errors.py

用法:
    python extract-gvm-errors.py log.txt
    python extract-gvm-errors.py log.txt --counts
    python extract-gvm-errors.py log.txt -o unique_errors.txt
    python extract-gvm-errors.py log.txt --filtered filtered_log.txt

功能:
 - 从指定日志文件中提取包含 "GVM error: DUT and REF xreg mismatch" 的行
 - 以行尾的 "DUT = 0x..., REF = 0x..." 两个值作为去重 key， 相同则视为重复并合并
 - 可选输出每个唯一条目的出现次数
 - 当提供 --filtered 参数时，输出一个文件，其内容为输入文件去掉了包含该错误行之后的部分
"""
import argparse
import re
import sys
from collections import OrderedDict

ERROR_MARK = "GVM error: DUT and REF xreg mismatch"
# 捕获 DUT 和 REF 的十六进制格式，允许空格
RE_DUT_REF = re.compile(r'DUT\s*=\s*(0x[0-9A-Fa-f]+)\s*,\s*REF\s*=\s*(0x[0-9A-Fa-f]+)')

def extract_unique_lines(lines):
    """
    返回 OrderedDict: key -> {'count': int, 'line': str}
    key 是 (dut_hex, ref_hex) 当能匹配到 DUT/REF 时；
    否则以完整行作为 key（避免丢失非标准格式的行）
    """
    results = OrderedDict()
    for raw in lines:
        line = raw.rstrip("\n")
        if ERROR_MARK in line:
            m = RE_DUT_REF.search(line)
            if m:
                key = (m.group(1).lower(), m.group(2).lower())
            else:
                key = ("_LINE_", line)
            if key in results:
                results[key]['count'] += 1
            else:
                results[key] = {'count': 1, 'line': line}
    return results

def main():
    p = argparse.ArgumentParser(description="从 log 中提取并合并 GVM xreg mismatch 错误行（按 DUT/REF 去重），并可输出过滤后的日志")
    p.add_argument("logfile", help="要解析的日志文件，或用 - 表示从 stdin 读取")
    p.add_argument("-o", "--output", help="提取错误信息输出文件（默认为 stdout）")
    p.add_argument("--counts", action="store_true", help="在输出中显示每个唯一条目的出现次数")
    p.add_argument("--filtered", help="输出文件（过滤后的日志，去掉包含 '{}' 的行）".format(ERROR_MARK))
    args = p.parse_args()

    # 打开输入并读取所有内容
    if args.logfile == "-":
        lines = sys.stdin.readlines()
    else:
        try:
            with open(args.logfile, "r", encoding="utf-8", errors="replace") as fin:
                lines = fin.readlines()
        except Exception as e:
            print(f"无法打开文件 {args.logfile}: {e}", file=sys.stderr)
            sys.exit(2)

    unique_results = extract_unique_lines(lines)

    # 写入提取结果
    if args.output:
        try:
            fout = open(args.output, "w", encoding="utf-8")
        except Exception as e:
            print(f"无法打开输出文件 {args.output}: {e}", file=sys.stderr)
            sys.exit(3)
    else:
        fout = sys.stdout

    for key, info in unique_results.items():
        count = info['count']
        line = info['line']
        if args.counts:
            fout.write(f"[{count}] {line}\n")
        else:
            fout.write(f"{line}\n")

    if fout is not sys.stdout:
        fout.close()

    # 如果指定 --filtered，则输出过滤后的日志（除去包含错误标记的行）
    if args.filtered:
        try:
            ffiltered = open(args.filtered, "w", encoding="utf-8")
        except Exception as e:
            print(f"无法打开过滤输出文件 {args.filtered}: {e}", file=sys.stderr)
            sys.exit(4)
        for raw in lines:
            if ERROR_MARK not in raw:
                ffiltered.write(raw)
        ffiltered.close()

if __name__ == "__main__":
    main()
