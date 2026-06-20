# ADR 0006 — C++ MC kernel as an optional, drop-in accelerator

## Status
Accepted

## Context
The Monte-Carlo path generator and payoff evaluator are the 95% hot loop of the whole system; a
bank writes them in C++/CUDA. The design spec calls for porting **one** product's path+payoff to
C++ via pybind11 to demonstrate the pattern and quote a real speedup — without turning the
project into a build-system exercise or breaking `pip install -e .` on a machine with no compiler.

## Decision
Ship the native kernel (`cpp/mc_kernel/autocall_kernel.cpp`) as an **optional accelerator behind
a stable Python interface** (`spdt/pricing/native.py`):

- The same `price_autocallable(...)` signature has **two implementations** — the C++ kernel and a
  vectorised NumPy reference computing the identical algorithm — plus a pure-Python scalar loop
  kept as the honest baseline.
- The extension is built **out-of-band** (`python cpp/build_kernel.py`), not by the package build,
  so the wheel installs with no compiler. `native.py` imports the compiled module if present and
  **falls back to the NumPy reference** otherwise; tests skip when it is absent.
- The C++ uses a fast xoshiro256** PRNG with an inline Box–Muller transform (the standard library
  RNG/`normal_distribution` dominate the loop and would erase the speedup).

## Consequences
- **The boundary is real.** One product's hot loop genuinely runs in C++; "the rest is the same
  pattern" is a true statement about a working seam, and a cross-check test asserts the kernel,
  the NumPy reference and the high-level `Autocallable` pricer agree to Monte-Carlo error.
- **Measured, honest speedups** (`cpp/benchmark.py`): ~1.5× vs already-vectorised NumPy (NumPy is
  itself compiled C), but ~20× vs an interpreted path-by-path Python loop and growing with the
  number of steps — the latter is the real reason desks leave Python. The kernel also streams
  `O(1)` memory per path versus NumPy's `O(paths × steps)`, so it scales to path counts that OOM
  the vectorised version.
- **CI stays green without a compiler.** The package and its tests do not depend on the build.
- **Cost / limitation.** A second implementation must be kept in sync with the Python pricer (the
  cross-check test guards this); the kernel covers one product and is single-threaded CPU. GPU and
  the rest of the catalog are declared as "same pattern," not implemented.
