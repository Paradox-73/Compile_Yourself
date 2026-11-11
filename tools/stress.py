"""Worst-case programs for both compilers: many globals, many arrays, long sums, deep nesting.

usage: python tools/stress.py --c1 C1.txt

Each program is compiled by tier2/v1c.py and by C1 (tier3.v1 compiled, run on the VM). Both
outputs must be identical, and the compiled program must print "ok". The sizes stay inside what
the brief allows (60,000-byte source) and inside the Tier 3 limits listed in the README.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VM = ROOT / "tools" / ("vm.exe" if os.name == "nt" else "vm")
CHECK = 'putc(111); putc(107); putc(10);'


def many_globals(n):
    decls = "".join(f"var g{i};\n" for i in range(n))
    return decls + f"func main() {{ g{n - 1} = 5; g0 = g{n - 1} + 1; if (g0 == 6) {{ {CHECK} }} }}\n"


def many_arrays(n):
    decls = "".join(f"array a{i}[2];\n" for i in range(n))
    return decls + f"func main() {{ a{n - 1}[1] = 7; a0[0] = a{n - 1}[1]; if (a0[0] == 7) {{ {CHECK} }} }}\n"


def long_sum(n):
    return "func main() { var x; x = 0" + "+1" * n + f"; if (x == {n}) {{ {CHECK} }} }}\n"


def long_compare(n):
    # 1 < 1 is 0, 0 < 1 is 1: the value flips with each comparison
    return "func main() { var x; x = 1" + "<1" * n + f"; if (x == {1 - n % 2}) {{ {CHECK} }} }}\n"


def nested_ifs(n):
    return ("func main() { var x; x = 0; " + "if (1) { x = x + 1; " * n + "}" * n
            + f" if (x == {n}) {{ {CHECK} }} }}\n")


def nested_parens(n):
    return ("func main() { var x; x = 1; x = " + "(" * n + "x" + " + 1)" * n
            + f"; if (x == {n + 1}) {{ {CHECK} }} }}\n")


CASES = [("globals_5000", many_globals(5000)), ("arrays_3500", many_arrays(3500)),
         ("sum_29900", long_sum(29900)), ("compare_10000", long_compare(10000)),
         ("ifs_2000", nested_ifs(2000)), ("parens_1000", nested_parens(1000))]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--c1", required=True, type=Path, help="tier3.v1 compiled by v1c.py")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="v1stress-"))
    failed = 0
    for name, src in CASES:
        assert len(src) <= 60000, name   # the brief allows at most 60,000 bytes
        py = subprocess.run([sys.executable, str(ROOT / "tier2" / "v1c.py")], input=src.encode(),
                            capture_output=True)
        c1 = subprocess.run([str(VM), str(args.c1), "10000000000"], input=src.encode(), capture_output=True)
        (work / f"{name}.txt").write_bytes(py.stdout)
        out = subprocess.run([str(VM), str(work / f"{name}.txt")], input=b"", capture_output=True).stdout
        ok = py.returncode == 0 and c1.returncode == 0 and py.stdout == c1.stdout and out == b"ok\n"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:<14} {len(src):>6} bytes  v1c exit {py.returncode}, "
              f"C1 exit {c1.returncode}, same output: {py.stdout == c1.stdout}, prints {out!r}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
