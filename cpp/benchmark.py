"""Benchmark the native C++ MC kernel against the NumPy reference and quote the speedup.

    python cpp/build_kernel.py   # build the kernel first
    python cpp/benchmark.py
"""

from __future__ import annotations

import time

from spdt.pricing.native import (
    HAVE_NATIVE,
    price_autocallable_native,
    price_autocallable_python_loop,
    price_autocallable_reference,
)

BASE = dict(
    spot=100.0, r=0.06, q=0.013, sigma=0.2, obs_times=(0.25, 0.5, 0.75, 1.0),
    notional=100.0, coupon_rate=0.02, autocall_level=1.0, coupon_barrier=0.7, knock_in=0.6, seed=0,
)


def _timed(fn, n_paths) -> tuple[float, float]:
    start = time.perf_counter()
    result = fn(**BASE, n_paths=n_paths)
    return result.price, time.perf_counter() - start


def main() -> None:
    if not HAVE_NATIVE:
        raise SystemExit("native kernel not built; run `python cpp/build_kernel.py`")

    # Pure-Python loop is ~1000× slower, so time it on fewer paths and rescale.
    py_paths, big_paths = 200_000, 2_000_000
    py_price, py_t = _timed(price_autocallable_python_loop, py_paths)
    py_t_per_path = py_t / py_paths
    ref_price, ref_t = _timed(price_autocallable_reference, big_paths)
    nat_price, nat_t = _timed(price_autocallable_native, big_paths)
    nat_per_path = nat_t / big_paths

    print(f"paths (C++/NumPy)  : {big_paths:,}   (Python loop timed on {py_paths:,}, rescaled)")
    print(f"pure-Python loop   : {py_price:8.4f}   {py_t_per_path*big_paths*1e3:10.1f} ms (extrapolated)")
    print(f"reference (NumPy)  : {ref_price:8.4f}   {ref_t*1e3:10.1f} ms")
    print(f"native (C++)       : {nat_price:8.4f}   {nat_t*1e3:10.1f} ms")
    print(f"price agreement    : {abs(ref_price - nat_price):.4f} (MC noise; different RNGs)")
    print(f"C++ vs NumPy       : {ref_t / nat_t:6.1f}x")
    print(f"C++ vs Python loop : {py_t_per_path / nat_per_path:6.0f}x")
    print("memory             : C++ streams O(1) per path; NumPy allocates O(paths×steps).")


if __name__ == "__main__":
    main()
