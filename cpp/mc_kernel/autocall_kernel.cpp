// Hot Monte-Carlo kernel: single-asset autocallable path generation + payoff (L4).
//
// This is the 95% hot loop a bank writes in C++/CUDA. We port exactly one product's path +
// payoff to demonstrate the pattern and quote a real speedup against the NumPy reference in
// spdt/pricing/native.py (same algorithm, same struck-at-spot conventions as the Python
// Autocallable). Everything else in SPDT stays in Python behind the same interface; only this
// inner loop crosses into C++.
//
// Build: python cpp/build_kernel.py   (compiles into spdt/pricing/_spdt_mc*.so)

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <cmath>
#include <cstdint>
#include <vector>

namespace py = pybind11;

// xoshiro256** — a fast, high-quality PRNG (Blackman & Vigna). std::mt19937_64 and
// std::normal_distribution dominate the runtime of the inner loop, so we replace both with a
// fast generator and an inline Box–Muller transform; that is what turns the C++ port into an
// actual speedup over already-vectorised NumPy rather than a wash.
struct Xoshiro {
  uint64_t s[4];
  static uint64_t splitmix(uint64_t &x) {
    uint64_t z = (x += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
  }
  explicit Xoshiro(uint64_t seed) {
    for (int i = 0; i < 4; ++i) s[i] = splitmix(seed);
  }
  static uint64_t rotl(uint64_t x, int k) { return (x << k) | (x >> (64 - k)); }
  uint64_t next() {
    const uint64_t result = rotl(s[1] * 5, 7) * 9;
    const uint64_t t = s[1] << 17;
    s[2] ^= s[0]; s[3] ^= s[1]; s[1] ^= s[2]; s[0] ^= s[3]; s[2] ^= t;
    s[3] = rotl(s[3], 45);
    return result;
  }
  // Uniform in (0, 1).
  double uniform() { return (next() >> 11) * (1.0 / 9007199254740992.0) + 1e-16; }
};

// Price a struck single-underlying autocallable by Monte Carlo. Levels are fractions of the
// initial fixing (= spot). Mirrors spdt.products.catalog.Autocallable with memory off.
py::dict price_autocallable(double spot, double r, double q, double sigma,
                            std::vector<double> obs_times, double notional,
                            double coupon_rate, double autocall_level,
                            double coupon_barrier, double knock_in, long n_paths,
                            unsigned long long seed) {
  const int n_obs = static_cast<int>(obs_times.size());
  std::vector<double> drift(n_obs), diffusion(n_obs), disc(n_obs);
  double prev = 0.0;
  for (int i = 0; i < n_obs; ++i) {
    const double dt = obs_times[i] - prev;
    prev = obs_times[i];
    drift[i] = (r - q - 0.5 * sigma * sigma) * dt;
    diffusion[i] = sigma * std::sqrt(dt);
    disc[i] = std::exp(-r * obs_times[i]);
  }

  Xoshiro gen(seed ? seed : 0x123456789abcdefULL);
  const int last = n_obs - 1;
  double sum = 0.0, sum_sq = 0.0;

  // Box–Muller produces two normals per call; cache the spare.
  bool has_spare = false;
  double spare = 0.0;
  auto next_normal = [&]() -> double {
    if (has_spare) { has_spare = false; return spare; }
    const double u1 = gen.uniform(), u2 = gen.uniform();
    const double radius = std::sqrt(-2.0 * std::log(u1));
    const double angle = 6.283185307179586 * u2;
    spare = radius * std::sin(angle);
    has_spare = true;
    return radius * std::cos(angle);
  };

  for (long p = 0; p < n_paths; ++p) {
    double log_s = std::log(spot);
    bool alive = true;
    double pv = 0.0;
    for (int i = 0; i < n_obs; ++i) {
      log_s += drift[i] + diffusion[i] * next_normal();
      const double ratio = std::exp(log_s) / spot;  // S_t / S_0
      if (alive && ratio >= coupon_barrier) pv += disc[i] * coupon_rate * notional;
      if (i < last) {
        if (alive && ratio >= autocall_level) {
          pv += disc[i] * notional;
          alive = false;
        }
      } else if (alive) {
        const double principal = (ratio <= knock_in) ? notional * ratio : notional;
        pv += disc[i] * principal;
      }
    }
    sum += pv;
    sum_sq += pv * pv;
  }

  const double mean = sum / static_cast<double>(n_paths);
  const double variance = sum_sq / static_cast<double>(n_paths) - mean * mean;
  const double std_error = std::sqrt(variance / static_cast<double>(n_paths));

  py::dict result;
  result["price"] = mean;
  result["std_error"] = std_error;
  result["n_paths"] = n_paths;
  return result;
}

PYBIND11_MODULE(_spdt_mc, m) {
  m.doc() = "SPDT native Monte-Carlo kernel (autocallable path + payoff).";
  m.def("price_autocallable", &price_autocallable, "Price a struck autocallable by MC.",
        py::arg("spot"), py::arg("r"), py::arg("q"), py::arg("sigma"), py::arg("obs_times"),
        py::arg("notional"), py::arg("coupon_rate"), py::arg("autocall_level"),
        py::arg("coupon_barrier"), py::arg("knock_in"), py::arg("n_paths"), py::arg("seed"));
}
