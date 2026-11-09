"""Run a v1 compiler on the test corpus and on generated programs, checking each against v1ref.

usage: python tools/run_tests.py --compiler "python tier2/v1c.py" [--gen N] [--seed S]
           [--jobs J] [--steps LIMIT] [-k SUBSTRING] [-v]

Each program is compiled (stdin -> stdout, at most 60 s), run on the VM with its input
(at most LIMIT steps), and its output is compared byte for byte with the expected output.
Corpus programs (tests/v1/*.v1) also check that v1ref still reproduces their .out file, and
tests/v1/invalid.txt checks that v1ref rejects each program in it.
Exit code 0 only when everything passes. Files of failing cases are kept and their folder printed.
"""
import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
CORPUS = ROOT / "tests" / "v1"
sys.path.insert(0, str(TOOLS))
import v1gen  # noqa: E402
import v1ref  # noqa: E402

COMPILE_TIMEOUT = 60


def corpus_cases(pattern):
    for src in sorted(CORPUS.glob("*.v1")):
        if pattern and pattern not in src.stem:
            continue
        inp = src.with_suffix(".in")
        out = src.with_suffix(".out")
        yield {"name": src.stem, "src": src.read_bytes(), "input": inp.read_bytes() if inp.exists() else b"",
               "expected": out.read_bytes() if out.exists() else None, "corpus": True}


def run_case(case, args, work):
    d = work / case["name"]
    d.mkdir()
    (d / "prog.v1").write_bytes(case["src"])
    (d / "input").write_bytes(case["input"])
    res = {"name": case["name"], "steps": None, "compile": None, "dir": d}
    if case.get("seed") is not None:
        try:
            case["src"], case["input"], case["expected"] = v1gen.generate(case["seed"])
        except v1ref.V1Error as e:
            return dict(res, status="GEN-ERROR", detail=f"generator made a program v1ref rejects: {e}")
        (d / "prog.v1").write_bytes(case["src"])
        (d / "input").write_bytes(case["input"])
    else:
        ref = subprocess.run([sys.executable, str(TOOLS / "v1ref.py"), str(d / "prog.v1")],
                             input=case["input"], capture_output=True)
        if ref.returncode:
            return dict(res, status="REF-ERROR", detail=ref.stderr.decode(errors="replace").strip())
        if case["expected"] is None:
            return dict(res, status="NO-OUT", detail="missing .out file")
        if ref.stdout != case["expected"]:
            (d / "v1ref.out").write_bytes(ref.stdout)
            return dict(res, status="STALE-OUT", detail="v1ref output differs from the .out file")
    (d / "expected").write_bytes(case["expected"])

    t0 = time.perf_counter()
    try:
        with open(d / "prog.txt", "wb") as fh:
            comp = subprocess.run(args.compiler, shell=True, input=case["src"], stdout=fh,
                                  stderr=subprocess.PIPE, timeout=COMPILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return dict(res, status="COMPILE-TIMEOUT", detail=f"over {COMPILE_TIMEOUT} s")
    res["compile"] = time.perf_counter() - t0
    if comp.returncode:
        return dict(res, status="COMPILE-ERROR", detail=comp.stderr.decode(errors="replace").strip()[-300:])

    env = dict(os.environ, VM_STATS="1")
    vm = subprocess.run([str(args.vm), str(d / "prog.txt"), str(args.steps)], input=case["input"],
                        capture_output=True, env=env)
    (d / "actual").write_bytes(vm.stdout)
    err = vm.stderr.decode(errors="replace")
    m = re.search(r"(?:halted|timeout) after (\d+) steps", err)
    res["steps"] = int(m.group(1)) if m else None
    if vm.returncode == 3:
        return dict(res, status="TIMEOUT", detail=err.strip())
    if vm.returncode:
        return dict(res, status="VM-ERROR", detail=err.strip())
    if vm.stdout != case["expected"]:
        exp, act = case["expected"], vm.stdout
        i = next((k for k in range(min(len(exp), len(act))) if exp[k] != act[k]), min(len(exp), len(act)))
        return dict(res, status="WRONG", detail=f"first difference at byte {i}: expected {exp[i:i + 12]!r}, "
                                                f"got {act[i:i + 12]!r} ({len(exp)} vs {len(act)} bytes)")
    return dict(res, status="PASS", detail="")


def check_invalid(pattern):
    """Each case in invalid.txt must be rejected by v1ref with a message containing its header text."""
    text = (CORPUS / "invalid.txt").read_text()
    failures, count = [], 0
    for chunk in text.split("\n### ")[1:]:
        want, _, src = chunk.partition("\n")
        if pattern and pattern not in want:
            continue
        count += 1
        try:
            v1ref.run(src.encode(), b"", 100000)
            failures.append(f"accepted: {src.strip()!r}")
        except v1ref.V1Error as e:
            if want not in str(e):
                failures.append(f"wanted {want!r}, got {e} for {src.strip()!r}")
    return count, failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compiler", required=True, help="command reading v1 on stdin, writing the program on stdout")
    ap.add_argument("--gen", type=int, default=50, help="number of generated programs (default 50)")
    ap.add_argument("--seed", type=int, default=1, help="first generator seed (default 1)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--steps", type=int, default=100_000_000, help="VM step limit (default 10^8)")
    ap.add_argument("--vm", type=Path, default=TOOLS / ("vm.exe" if os.name == "nt" else "vm"))
    ap.add_argument("-k", dest="pattern", help="only corpus programs whose name contains this; skips generated ones")
    ap.add_argument("-v", action="store_true", help="print every case, not only failures")
    args = ap.parse_args()

    cases = list(corpus_cases(args.pattern))
    if not args.pattern:
        cases += [{"name": f"gen_{s}", "seed": s, "src": b"", "input": b""} for s in range(args.seed, args.seed + args.gen)]
    work = Path(tempfile.mkdtemp(prefix="v1tests-"))
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda c: run_case(c, args, work), cases))

    bad = [r for r in results if r["status"] != "PASS"]
    for r in results:
        if args.v or r["status"] != "PASS":
            steps = f"{r['steps']:>11,}" if r["steps"] is not None else " " * 11
            comp = f"{r['compile']:6.2f}s" if r["compile"] is not None else " " * 7
            print(f"{r['status']:<15} {r['name']:<34} steps {steps}  compile {comp}  {r['detail']}")
    inv_count, inv_fail = check_invalid(args.pattern)
    for f in inv_fail:
        print(f"INVALID-CHECK   {f}")

    ran = [r for r in results if r["steps"] is not None]
    timed = [r for r in results if r["compile"] is not None]
    print(f"\n{len(results) - len(bad)}/{len(results)} programs passed "
          f"({sum(not r['name'].startswith('gen_') for r in results)} corpus, "
          f"{sum(r['name'].startswith('gen_') for r in results)} generated); "
          f"{inv_count - len(inv_fail)}/{inv_count} invalid programs rejected by v1ref")
    if ran:
        print(f"steps: total {sum(r['steps'] for r in ran):,}, max {max(r['steps'] for r in ran):,}")
        print("most steps:      " + ", ".join(f"{r['name']} {r['steps']:,}"
                                             for r in sorted(ran, key=lambda r: -r["steps"])[:5]))
    if timed:
        print(f"compile: total {sum(r['compile'] for r in timed):.1f}s, max {max(r['compile'] for r in timed):.2f}s")
        print("slowest compile: " + ", ".join(f"{r['name']} {r['compile']:.2f}s"
                                             for r in sorted(timed, key=lambda r: -r["compile"])[:5]))
    for r in results:
        if r["status"] == "PASS":
            shutil.rmtree(r["dir"], ignore_errors=True)
    if bad:
        print(f"failing cases kept in {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if bad or inv_fail else 0


if __name__ == "__main__":
    sys.exit(main())
