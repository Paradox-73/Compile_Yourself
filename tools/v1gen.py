"""Generate random valid v1 programs that terminate quickly.

usage: python tools/v1gen.py --seed S [--input-out FILE] > prog.v1

The same seed always gives the same program and input. Every program is run on v1ref
before it is returned: it must compile, avoid undefined behaviour and stay under MAX_OPS
interpreter operations, else the next attempt for that seed is tried.
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v1ref  # noqa: E402

# One v1ref operation costs very roughly 10 to 100 machine steps once compiled, so this keeps
# runs near 10^6 steps.
MAX_OPS = 30000
LITERALS = [0, 1, 2, 3, 7, 10, 31, 48, 100, 127, 128, 255, 256, 1000, 32767, 32768, 46340, 46341,
            65535, 65536, 1000000, 16777216, 1073741824, 2147483646, 2147483647]
RESERVED = v1ref.KEYWORDS | set(v1ref.BUILTINS) | {"pr", "pr_d", "pr_x", "pr_s", "cl", "mix", "h"}
CMP_OPS = ["<", "<=", ">", ">=", "==", "!="]

HELPERS = """\
var h; // running checksum of every value passed to mix
var pr_x;
var pr_s;
func pr_d(p) {
  var d; d = 0;
  while (pr_x <= 0 - p) { pr_x = pr_x + p; d = d + 1; }
  if (d > 0) { pr_s = 1; }
  if (pr_s) { putc(48 + d); }
}
func pr(x) { // decimal, works for -2147483648 because it counts on the negative side
  if (x < 0) { putc(45); pr_x = x; } else { pr_x = -x; }
  pr_s = 0;
  pr_d(1000000000); pr_d(100000000); pr_d(10000000); pr_d(1000000); pr_d(100000);
  pr_d(10000); pr_d(1000); pr_d(100); pr_d(10);
  putc(48 - pr_x); putc(10);
}
func cl(v, n) { if (v < 0) { return 0; } if (v >= n) { return n - 1; } return v; }
func mix(v) { h = h * 31 + v; return v; }
"""


class Fn:
    def __init__(self, name, params, recursive):
        self.name, self.params, self.recursive = name, params, recursive
        self.cheap = True   # no loops and calls only cheap functions, so safe inside expressions and loops


class Gen:
    def __init__(self, rng):
        self.r = rng
        self.used = set(RESERVED)
        self.globals, self.arrays, self.funcs = [], [], []
        self.lines = []

    def name(self, long=False):
        r = self.r
        while True:
            n = 24 if long or r.random() < 0.08 else r.randint(1, 8)
            first = r.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
            s = first + "".join(r.choice("abcdefghijklmnopqrstuvwxyz_0123456789ABCXYZ") for _ in range(n - 1))
            if s not in self.used:
                self.used.add(s)
                return s

    def emit(self, depth, text):
        if self.r.random() < 0.1:
            text += "  // " + self.r.choice(["note", "x = y; // not code", "{ } ( ) [ ]", "while (1) {"])
        self.lines.append("  " * depth + text)

    # expressions return (text, precedence level): 1 comparison, 2 additive, 3 product, 4 unary, 5 primary
    def expr(self, env, depth):
        r = self.r
        if depth <= 0 or r.random() < 0.25:
            return self.leaf(env, depth)
        k = r.random()
        if k < 0.12:
            t, lv = self.expr(env, depth - 1)
            return ("-" if r.random() < 0.7 else "- ") + (t if lv >= 4 else f"({t})"), 4
        if k < 0.17:
            t, _ = self.expr(env, depth - 1)
            return f"({t})", 5
        op, lv = r.choice([("*", 3), ("+", 2), ("-", 2), ("+", 2), (r.choice(CMP_OPS), 1)])
        a, la = self.expr(env, depth - 1)
        b, lb = self.expr(env, depth - 1)
        a = a if la >= lv else f"({a})"
        b = b if lb > lv else f"({b})"
        return f"{a} {op} {b}", lv

    def leaf(self, env, depth):
        r = self.r
        k = r.random()
        if depth <= 0 or k < 0.3 or not env["read"]:
            if k >= 0.3 and env["read"]:
                return r.choice(env["read"]), 5
            v = r.choice(LITERALS) if r.random() < 0.6 else r.randint(0, 99)
            return str(v), 5
        if k < 0.65:
            return r.choice(env["read"]), 5
        if k < 0.8 and self.arrays:
            return self.index(env, depth), 5
        if k < 0.85 and env["getc"]:
            return "getc()", 5
        if k < 0.92:
            e, _ = self.expr(env, depth - 1)
            return f"mix({e})", 5
        calls = [f for f in self.funcs if f.cheap and not f.recursive]
        if calls and depth > 0:
            return self.call(r.choice(calls), env, depth - 1), 5
        return r.choice(env["read"]), 5

    def index(self, env, depth):
        name, size = self.r.choice(self.arrays)
        if self.r.random() < 0.3:
            return f"{name}[{self.r.randrange(size)}]"
        e, _ = self.expr(env, min(depth, 2))
        return f"{name}[cl({e}, {size})]"

    def call(self, fn, env, depth, rec_depth=None):
        args = [self.expr(env, min(depth, 2))[0] for _ in fn.params]
        if fn.recursive:
            args[0] = rec_depth
        return f"{fn.name}({', '.join(args)})"

    # statements
    def block(self, env, depth, n, loops):
        for _ in range(n):
            self.statement(env, depth, loops)

    def statement(self, env, depth, loops):
        r = self.r
        k = r.random()
        if k < 0.22 and env["write"]:
            self.emit(depth, f"{r.choice(env['write'])} = {self.expr(env, 3)[0]};")
        elif k < 0.32 and self.arrays:
            self.emit(depth, f"{self.index(env, 2)} = {self.expr(env, 3)[0]};")
        elif k < 0.42:
            self.declare(env, depth)
        elif k < 0.52:
            self.emit(depth, f"{r.choice(['putc', 'pr', 'mix'])}({self.expr(env, 3)[0]});")
        elif k < 0.62 and depth < 6:
            self.emit(depth, f"if ({self.expr(env, 3)[0]}) {{")
            self.sub_block(env, depth, loops)
            if r.random() < 0.5:
                self.emit(depth, "} else {")
                self.sub_block(env, depth, loops)
            self.emit(depth, "}")
        elif k < 0.72 and depth < 6 and loops < 2:
            self.loop(env, depth, loops)
        elif k < 0.8:
            calls = [f for f in self.funcs if not f.recursive and (f.cheap or loops == 0)]
            if calls:
                fn = r.choice(calls)
                self.emit(depth, self.call(fn, env, 2) + ";")
                env["fn"].cheap &= fn.cheap
        elif k < 0.84 and env["fn"].name != "main" and depth > 1:
            self.emit(depth, f"return {self.expr(env, 3)[0]};")
        else:
            self.emit(depth, f"mix({self.expr(env, 2)[0]});")

    def sub_block(self, env, depth, loops):
        saved = (list(env["read"]), list(env["write"]), set(env["block"]))
        env["block"] = set()
        if env["read"] and self.r.random() < 0.15:
            # redeclare an outer local inside this block; the outer one is visible again after the block
            outer = [n for n in env["locals"] if n in env["read"]]
            if outer:
                n = self.r.choice(outer)
                env["read"].remove(n)   # inside `var n; n = e;` the name n already means the new local
                self.emit(depth + 1, f"var {n}; {n} = {self.expr(env, 2)[0]};")
                env["read"].append(n)
                env["block"].add(n)
        self.block(env, depth + 1, self.r.randint(0, 3), loops)
        env["read"], env["write"], env["block"] = saved

    def declare(self, env, depth):
        n = self.name()
        e = self.expr(env, 3)[0]
        self.emit(depth, f"var {n}; {n} = {e};")
        env["read"].append(n)
        env["write"].append(n)
        env["locals"].append(n)
        env["block"].add(n)

    def loop(self, env, depth, loops):
        r = self.r
        i = self.name()
        trips = r.randint(0, 6 if loops == 0 else 3)
        env["fn"].cheap = False
        if r.random() < 0.5:
            self.emit(depth, f"var {i}; {i} = 0;")
            self.emit(depth, f"while ({i} < {trips}) {{")
            step = f"{i} = {i} + 1;"
        else:
            self.emit(depth, f"var {i}; {i} = {trips};")
            self.emit(depth, f"while ({r.choice([f'{i} > 0', f'0 < {i}', f'{i} != 0', f'{i} >= 1'])}) {{")
            step = f"{i} = {i} - 1;"
        env["read"].append(i)
        env["block"].add(i)
        self.sub_block(env, depth, loops + 1)
        self.emit(depth + 1, step)
        self.emit(depth, "}")

    def function(self, recursive):
        r = self.r
        name = self.name(long=r.random() < 0.1)
        nparams = r.randint(1 if recursive else 0, 8)
        params = []
        for k in range(nparams):
            free = [g for g in self.globals if g not in params]
            if k > 0 and free and r.random() < 0.15:
                params.append(r.choice(free))
            else:
                params.append(self.name())
        fn = Fn(name, params, recursive)
        shadow = [g for g in self.globals if g not in params and r.random() < 0.2]
        visible_globals = [g for g in self.globals if g not in params and g not in shadow]
        env = {"read": params + visible_globals, "write": params[1 if recursive else 0:] + visible_globals,
               "locals": [], "block": set(params), "fn": fn, "getc": True}
        self.lines.append(f"func {name}({', '.join(params)}) {{")
        for g in shadow:   # a local that hides a global for the whole function
            self.emit(1, f"var {g}; {g} = {self.expr(env, 2)[0]};")
            env["read"].append(g)
            env["write"].append(g)
            env["block"].add(g)
        if recursive:
            self.emit(1, f"if ({params[0]} < 1) {{ return {self.expr(env, 3)[0]}; }}")
            fn.cheap = False
        self.block(env, 1, r.randint(1, 5), 0)
        if recursive:
            v = self.name()
            self.emit(1, f"var {v}; {v} = {self.call(fn, env, 2, f'{params[0]} - 1')};")
            env["read"].append(v)
            self.emit(1, f"mix({v});")
        if r.random() < 0.8:
            self.emit(1, f"return {self.expr(env, 3)[0]};")
        self.lines.append("}")
        self.funcs.append(fn)

    def program(self):
        r = self.r
        for _ in range(r.randint(1, 5)):
            g = self.name()
            self.globals.append(g)
            self.lines.append(f"var {g};")
        for _ in range(r.randint(1, 3)):
            a, size = self.name(), r.choice([1, 2, 5, 16, 100, 1000, 60000 if r.random() < 0.2 else 10])
            self.arrays.append((a, size))
            self.lines.append(f"array {a}[{size}];")
        self.lines.append(HELPERS)
        for _ in range(r.randint(1, 7)):
            self.function(recursive=r.random() < 0.3)
        self.lines.append("func main() {")
        main = Fn("main", [], False)
        env = {"read": list(self.globals), "write": list(self.globals), "locals": [], "block": set(),
               "fn": main, "getc": False}
        c, n = self.name(), self.name()
        self.emit(1, f"var {c}; var {n}; {n} = 0; {c} = getc();")
        self.emit(1, f"while ({c} != -1) {{ mix({c}); {n} = {n} + 1;"
                     + (f" putc({c});" if r.random() < 0.5 else "") + f" {c} = getc(); }}")
        self.emit(1, f"pr({n}); pr(getc());")
        env["getc"] = True   # input is used up, so getc() here must return -1
        for fn in self.funcs:
            rec = str(r.choice([0, 1, 2, 5, 12, r.choice([300, 900]) if r.random() < 0.5 else 3])) if fn.recursive else None
            self.emit(1, f"pr({self.call(fn, env, 3, rec)});")
            if r.random() < 0.5:
                self.statement(env, 1, 0)
        self.block(env, 1, r.randint(2, 6), 0)
        for g in self.globals:
            self.emit(1, f"pr({g});")
        for a, size in self.arrays:
            i = self.name()
            self.emit(1, f"var {i}; {i} = 0;")
            self.emit(1, f"while ({i} < {min(size, 100)}) {{ mix({a}[{i}]); {i} = {i} + 1; }}")
        self.emit(1, "pr(h);")
        self.lines.append("}")
        return "\n".join(self.lines) + "\n"


def generate(seed):
    """Return (source bytes, input bytes, expected output bytes) for this seed."""
    for attempt in range(100):
        r = random.Random(seed * 1000 + attempt)
        src = Gen(r).program().encode()
        inp = bytes(r.randrange(256) for _ in range(r.choice([0, 1, 5, 20, 40])))
        try:
            out, _ = v1ref.run(src, inp, MAX_OPS)
        except (v1ref.BudgetExceeded, v1ref.V1Error):
            # the generator can reuse a name for a function and a variable; draw again
            continue
        return src, inp, out
    raise RuntimeError(f"seed {seed}: no program under {MAX_OPS} operations in 100 attempts")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--input-out", type=Path, help="write the program's input bytes here")
    args = ap.parse_args()
    src, inp, _ = generate(args.seed)
    sys.stdout.buffer.write(src)
    if args.input_out:
        args.input_out.write_bytes(inp)


if __name__ == "__main__":
    main()
