"""Reproducible workload matrix, with an actual OS process/job memory ceiling.

The local Job/RLIMIT_AS is NOT a claim that the host has only 4 GB RAM.
Use the container CI workflow for the separately constrained 4 GB environment.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from explorer.memory import constrain_process

PROSE = 'The project reviewed 1250 documents. The key result was an 18% increase in accuracy. The final metric is 42.'


def counters():
    if os.name != 'nt':
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return dict(peak_rss_mb=usage.ru_maxrss / 1024, cpu_seconds=usage.ru_utime + usage.ru_stime,
                    disk_read_bytes=usage.ru_inblock * 512)
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(key, ctypes.c_size_t) for key in
            ('peak_ws', 'ws', 'peak_pool', 'pool', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    class IO(ctypes.Structure):
        _fields_ = [(key, ctypes.c_ulonglong) for key in ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.GetCurrentProcess()
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb)
    io = IO()
    kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel.GetProcessIoCounters(handle, ctypes.byref(io))
    times = [ctypes.c_ulonglong() for _ in range(4)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
    kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in times])
    return dict(peak_rss_mb=memory.peak_ws / 1024**2, cpu_seconds=(times[2].value + times[3].value) / 10**7,
                disk_read_bytes=io.read_bytes)


def make_pdf(path, pages):
    import fitz
    with fitz.open() as document:
        for number in range(pages):
            page = document.new_page()
            page.insert_textbox(fitz.Rect(50, 50, 530, 700), 'Section %d\n\n%s\n\n%s' % (number + 1, PROSE, PROSE), fontsize=12)
        document.save(path, deflate=True)


def make_corpus(root, count):
    root.mkdir(exist_ok=True)
    last = root / ('batch-%03d' % ((count - 1) // 1000)) / ('document-%06d.txt' % (count - 1))
    if last.exists():
        return  # Fixtures are written in order; the benchmark verifies final counts.
    previous_folder = None
    for i in range(count):
        folder = root / ('batch-%03d' % (i // 1000))
        if folder != previous_folder:
            folder.mkdir(exist_ok=True)
            previous_folder = folder
        path = folder / ('document-%06d.txt' % i)
        if not path.exists():
            path.write_text(PROSE, encoding='utf-8')


def case(args):
    if not constrain_process(args.limit_mb):
        raise RuntimeError('OS memory ceiling was NOT applied')
    start = time.perf_counter()
    before = counters()
    if args.case == 'pages':
        from explorer.detect import detect
        from explorer.parsers import metadata
        from explorer.store import connect
        from explorer.summary import summarize, verify_claim
        path = Path(args.fixture)
        workspace = tempfile.TemporaryDirectory(prefix='summary-benchmark-', dir=args.workdir)
        db = connect(Path(workspace.name) / 'working.db')
        first = [None]
        def notice(event):
            if event['event'] == 'quick' and first[0] is None:
                first[0] = time.perf_counter() - start
        try:
            kind = detect(path)
            result = summarize(path, kind, db, metadata(path, kind), notice)
            elapsed = time.perf_counter() - start
            repeat_start = time.perf_counter()
            repeated = summarize(path, kind, db, metadata(path, kind))
            repeat_time = time.perf_counter() - repeat_start
            import fitz
            from explorer.summary import facts
            with fitz.open(path) as source_doc:
                evidence = [(bullet, source_doc[int(bullet['anchor'].split()[-1]) - 1].get_text('text', sort=True)) for bullet in result['bullets']]
            faithful = all(verify_claim(bullet['text'], original) for bullet, original in evidence)
            numeric = all(all(value in original for value in facts(bullet['text'])['numbers_dates']) for bullet, original in evidence)
            result_metrics = dict(time_to_first_summary=first[0], total_summary_seconds=elapsed,
                repeated_summary_seconds=repeat_time, summary_cache_enabled=False,
                new_request_id=result['key'] != repeated['key'], section_coverage=result['sections'] / args.size,
                numeric_accuracy=int(numeric), exact_source_check=faithful, selected_sections=len(result['bullets']),
                quality_method='Synthetic extractive faithfulness and coverage; no subjective AI quality score')
        finally:
            db.close()
            workspace.cleanup()
    else:
        from explorer.files import scan, page
        filename = Path(args.workdir) / ('index-%s-%s.db' % (args.limit_mb, args.size))
        count = scan(Path(args.fixture), filename, True)
        elapsed = time.perf_counter() - start
        query_start = time.perf_counter()
        rows, total = page(filename, query='document-', offset=max(0, args.size - 160))
        query_time = time.perf_counter() - query_start
        assert total == args.size, 'Incomplete corpus fixture'
        result_metrics = dict(index_seconds=elapsed, query_seconds=query_time, indexed_entries=count,
            matched_documents=total, visible_rows=len(rows), index_bytes=filename.stat().st_size)
    after = counters()
    measured_seconds = time.perf_counter() - start
    cpu = after['cpu_seconds'] - before['cpu_seconds']
    result_metrics.update(case=args.case, size=args.size, memory_limit_mb=args.limit_mb,
        memory_limit_enforced=True, peak_rss_mb=after['peak_rss_mb'], cpu_seconds=cpu,
        measured_seconds=measured_seconds,
        average_cpu_one_core_percent=cpu / max(.001, measured_seconds) * 100,
        process_read_bytes=after['disk_read_bytes'] - before['disk_read_bytes'])
    print(json.dumps(result_metrics))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=['pages', 'corpus'])
    parser.add_argument('--size', type=int)
    parser.add_argument('--fixture')
    parser.add_argument('--workdir', default=str(ROOT / '.data' / 'benchmarks'))
    parser.add_argument('--limit-mb', type=int, default=4096)
    parser.add_argument('--output', default=str(ROOT / 'docs' / 'benchmark-results.json'))
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    if args.case:
        case(args)
        return
    if not constrain_process(args.limit_mb):
        raise RuntimeError('Could not constrain benchmark process tree')
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    results = []
    for pages in ([1, 100] if args.quick else [1, 10, 100, 500, 1000, 5000]):
        fixture = workdir / ('pages-%s.pdf' % pages)
        if not fixture.exists():
            make_pdf(fixture, pages)
        output = subprocess.check_output([sys.executable, __file__, '--case', 'pages', '--size', str(pages),
            '--fixture', str(fixture), '--workdir', str(workdir), '--limit-mb', str(min(256, args.limit_mb))], text=True)
        result = json.loads(output)
        results.append(result)
        print(json.dumps(result), flush=True)
    for count in ([100] if args.quick else [100, 10000, 100000]):
        fixture = workdir / ('corpus-%s' % count)
        make_corpus(fixture, count)
        output = subprocess.check_output([sys.executable, __file__, '--case', 'corpus', '--size', str(count),
            '--fixture', str(fixture), '--workdir', str(workdir), '--limit-mb', str(min(256, args.limit_mb))], text=True)
        result = json.loads(output)
        results.append(result)
        print(json.dumps(result), flush=True)
    cgroup_4gb = False
    try:
        cgroup_4gb = int(Path('/sys/fs/cgroup/memory.max').read_text().strip()) <= 4 * 1024**3
    except (OSError, ValueError):
        pass
    report = dict(environment='Windows Job process-tree limit' if os.name == 'nt' else 'RLIMIT_AS within cgroup/host',
        process_tree_ceiling_mb=args.limit_mb, system_4gb_verified=cgroup_4gb,
        caveat='A process ceiling on the local host is not a 4 GB VM benchmark. CI container results must be reviewed separately.',
        results=results)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
