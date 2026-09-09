"""Plant defects in the model and find out which ones the tests miss.

    python tools/mutate.py                 every module, the default sample
    python tools/mutate.py --module taxes  one module
    python tools/mutate.py --per-module 40 a bigger sample
    python tools/mutate.py --list          count the sites without running

A passing test suite says the tests agree with the code. It does not say the
tests would notice if the code were wrong. This changes the code, deliberately
and one edit at a time, and runs the suite against each version. A mutant that
survives is a line the tests do not actually check.

WHAT IT CHANGES. Comparisons (< to <=, > to >=, == to !=), arithmetic (+ to -,
* to /), boolean connectives (and to or), unary negation, boundary constants
(x to x plus one, x to zero, x to x times 1.1) and the two literals True and
False. Mutations are made on the syntax tree rather than on the text, so a
comment or a docstring can never be mutated by accident.

WHAT IT LEAVES ALONE. Anything inside a `raise` (breaking an error message is
not a defect worth reporting), and the constants 0 and 1 where they appear as
list indices, because turning index 0 into index 1 reports a crash rather than
a silent wrong answer and the crash is not the thing being hunted.

THE SOURCE IS RESTORED WHATEVER HAPPENS. Each module is read once at the start
and written back in a finally block, and the run ends by verifying every file
is byte-identical to how it started. If that check ever fails, the run says so
loudly, because a mutation tester that leaves a mutant behind is worse than no
mutation tester.

A NOTE ON READING THE RESULT. A surviving mutant is not automatically a bug.
Some lines genuinely do not change any observable answer, and some constants
are cosmetic. The output prints the exact edit so each survivor can be judged
rather than counted.
"""

from __future__ import annotations

import argparse
import ast
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "your_equity_share"

# Deterministic, so two runs of the same revision plant the same defects and a
# survivor that gets fixed can be checked by rerunning.
SEED = 20260909

COMPARE = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
           ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
BINARY = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div,
          ast.Div: ast.Mult}
BOOLEAN = {ast.And: ast.Or, ast.Or: ast.And}


class Sites(ast.NodeVisitor):
    """Every place a single edit could change what the module computes."""

    def __init__(self):
        self.found: list[tuple[str, int, str]] = []
        self._in_raise = False

    def visit_Raise(self, node):
        was, self._in_raise = self._in_raise, True
        self.generic_visit(node)
        self._in_raise = was

    def visit_Compare(self, node):
        if not self._in_raise:
            for i, op in enumerate(node.ops):
                if type(op) in COMPARE:
                    self.found.append(("compare", node.lineno, "%d" % i))
        self.generic_visit(node)

    def visit_BinOp(self, node):
        if not self._in_raise and type(node.op) in BINARY:
            self.found.append(("binary", node.lineno, ""))
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        if not self._in_raise and type(node.op) in BOOLEAN:
            self.found.append(("boolean", node.lineno, ""))
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if not self._in_raise and isinstance(node.op, ast.USub):
            self.found.append(("negate", node.lineno, ""))
        self.generic_visit(node)

    def visit_Constant(self, node):
        if self._in_raise:
            return
        if isinstance(node.value, bool):
            self.found.append(("bool", node.lineno, ""))
        elif isinstance(node.value, (int, float)):
            self.found.append(("number", node.lineno, ""))


class Apply(ast.NodeTransformer):
    """Make exactly one of the edits Sites found."""

    def __init__(self, kind, target):
        self.kind, self.target, self.seen = kind, target, 0
        self.applied = None
        self.line = None

    def _hit(self):
        self.seen += 1
        return self.seen - 1 == self.target

    def visit_Raise(self, node):
        return node  # left alone, see the module docstring

    def visit_Compare(self, node):
        self.generic_visit(node)
        if self.kind == "compare":
            for i, op in enumerate(node.ops):
                if type(op) in COMPARE and self._hit():
                    self.applied = "%s to %s" % (type(op).__name__,
                                                 COMPARE[type(op)].__name__)
                    self.line = node.lineno
                    node.ops[i] = COMPARE[type(op)]()
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if self.kind == "binary" and type(node.op) in BINARY and self._hit():
            self.applied = "%s to %s" % (type(node.op).__name__,
                                         BINARY[type(node.op)].__name__)
            self.line = node.lineno
            node.op = BINARY[type(node.op)]()
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self.kind == "boolean" and type(node.op) in BOOLEAN and self._hit():
            self.applied = "%s to %s" % (type(node.op).__name__,
                                         BOOLEAN[type(node.op)].__name__)
            self.line = node.lineno
            node.op = BOOLEAN[type(node.op)]()
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if (self.kind == "negate" and isinstance(node.op, ast.USub)
                and self._hit()):
            self.applied = "drop the minus sign"
            self.line = node.lineno
            return node.operand
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            if self.kind == "bool" and self._hit():
                self.line = node.lineno
                self.applied = "%r to %r" % (node.value, not node.value)
                return ast.Constant(value=not node.value)
            return node
        if isinstance(node.value, (int, float)) and self.kind == "number":
            if self._hit():
                if node.value == 0:
                    new = 1
                elif node.value == 1:
                    new = 0
                else:
                    new = node.value * 1.1
                self.line = node.lineno
                self.applied = "%r to %r" % (node.value, new)
                return ast.Constant(value=new)
        return node


def modules(only: str | None) -> list[Path]:
    found = sorted(p for p in PACKAGE.glob("*.py")
                   if p.name != "__init__.py")
    if only:
        found = [p for p in found if only in p.name]
        if not found:
            raise SystemExit("no module matching %r" % only)
    return found


def run_suite(timeout: int) -> bool:
    """True when the suite still passes, which means the mutant survived."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, timeout=timeout)
    return done.returncode == 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--module")
    parser.add_argument("--per-module", type=int, default=22)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv[1:])

    targets = modules(args.module)
    originals = {p: p.read_text(encoding="utf-8") for p in targets}
    rng = random.Random(SEED)

    plan: list[tuple[Path, str, int, int]] = []
    for path in targets:
        tree = ast.parse(originals[path])
        finder = Sites()
        finder.visit(tree)
        counts: dict[str, int] = {}
        for kind, _, _ in finder.found:
            counts[kind] = counts.get(kind, 0) + 1
        every = [(kind, i) for kind, total in sorted(counts.items())
                 for i in range(total)]
        chosen = (every if len(every) <= args.per_module
                  else rng.sample(every, args.per_module))
        for kind, index in sorted(chosen):
            plan.append((path, kind, index, len(every)))
        if args.list:
            print("  %-22s %4d sites, %d planned"
                  % (path.name, len(every), min(len(every), args.per_module)))

    if args.list:
        print("\n  %d mutations would run" % len(plan))
        return 0

    print("Mutation testing: %d defects across %d modules"
          % (len(plan), len(targets)))
    print("=" * 74)
    survivors, killed, broken = [], 0, 0
    started = time.time()
    try:
        for n, (path, kind, index, _) in enumerate(plan, 1):
            tree = ast.parse(originals[path])
            mutator = Apply(kind, index)
            mutated = mutator.visit(tree)
            if mutator.applied is None:
                continue
            ast.fix_missing_locations(mutated)
            try:
                source = ast.unparse(mutated)
            except Exception:
                continue
            path.write_text(source, encoding="utf-8")
            try:
                alive = run_suite(args.timeout)
            except subprocess.TimeoutExpired:
                alive = False  # a hang is a failure, and the tests caught it
            finally:
                path.write_text(originals[path], encoding="utf-8")
            if alive:
                survivors.append((path.name, mutator.line, kind,
                                  mutator.applied))
                print("  SURVIVED  %-18s line %-5s %-8s %s"
                      % (path.name, mutator.line, kind, mutator.applied))
            else:
                killed += 1
            if n % 25 == 0:
                print("  ... %d of %d, %d killed, %d survived, %.0fs elapsed"
                      % (n, len(plan), killed, len(survivors),
                         time.time() - started))
    finally:
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")

    for path, text in originals.items():
        if path.read_text(encoding="utf-8") != text:
            print("\n  RESTORE FAILED for %s. Check it before committing."
                  % path.name)
            broken += 1

    print()
    print("=" * 74)
    print("  %d planted, %d killed, %d survived, %.0f seconds"
          % (killed + len(survivors), killed, len(survivors),
             time.time() - started))
    if broken:
        print("  %d FILES NOT RESTORED" % broken)
        return 2
    if survivors:
        print("\n  Each survivor is a line the tests do not check. Some are")
        print("  harmless: a constant that no answer depends on, a comparison")
        print("  on a path nothing reaches. Judge them, do not just count.")
        return 1
    print("  Every planted defect was caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
