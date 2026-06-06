"""model.py — the 4-channel hierarchical latent-quality model for the restaurant ranker.

Ports the frozen spike-022 (`model_prestige.py`) formulation — a Bayesian factor model
that fuses prestige + review-rating + review-count + ordinal-gate + booking-fill into one
latent quality ``q`` per venue, partial-pooled by cuisine — into clean, generalized,
TESTABLE code. The science is proven and FROZEN (spike-022 0-divergence real-data fit,
spike-014 simulation-recovery q-corr 0.98). This module does NOT re-derive the model or
re-tune priors; it ports the math verbatim and decomposes it into pure functions.

Decomposition (mirrors Phase-1's isolated gather_source seam):

  prepare_model_data(corpus, reviews, booking, *, s_sources) -> ModelData   PURE (no PyMC)
  build_model(md)                                            -> pm.Model    PURE construct
  fit(model, *, seed, draws, tune, target_accept)            -> InferenceData  THE seam
  summarize_posterior(idata, venue_meta)                     -> RankingResult PURE
  main(argv)                                                 -> int          CLI

HONESTY RAIL (MODEL-04): a venue missing the fill channel is simply NOT in the ``readable``
index, so the fill likelihood never constrains its q — its posterior stays wide. There is
no missing-value branch and no zero-fill / imputation anywhere. The honesty guarantee is
delivered by data SHAPE, not by special-casing.

IMPORT DISCIPLINE: ``prepare_model_data`` and ``summarize_posterior`` are import-light
(numpy + stdlib only) so they are unit-testable WITHOUT PyMC installed. ``pymc`` / ``arviz``
are imported INSIDE ``build_model`` / ``fit`` / ``summarize_posterior`` so the module imports
cleanly on a PyMC-less interpreter and the source-guard tests run anywhere.

Python: model fit requires a uv-managed Python 3.12 venv (system 3.10 cannot compile the
PyTensor C backend). The pure functions run on any interpreter with numpy.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Resolve sibling modules (booking.gate_level, cityconfig.load_city) — same
# __file__-relative sys.path pattern corpus.py / booking.py use.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from booking import gate_level  # noqa: E402  (3-arg in-repo signature)
from cityconfig import load_city, UnknownCityError  # noqa: E402

__all__ = [
    "ModelData",
    "RankingResult",
    "prepare_model_data",
    "build_model",
    "fit",
    "summarize_posterior",
    "main",
]


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ModelData:
    """Arrays + coords + metadata produced by prepare_model_data (PURE, no PyMC)."""

    # per-venue arrays (length N, venue order)
    prestige: np.ndarray          # int, clamped to s_sources
    gate_lv: np.ndarray           # int 0..4 ordinal gate level
    cuisine_idx: np.ndarray       # int, index into coords["cuisine"]
    # reviews arrays — None when the reviews channel was skipped (REV-02)
    rating: np.ndarray | None
    n_rev: np.ndarray | None      # review count (>=1)
    logcount_z: np.ndarray | None
    # readable subset (fill channel) — indices into the venue axis
    readable: np.ndarray          # int indices; empty if no readable venues
    N_slots: np.ndarray           # float, gathered over readable only
    filled: np.ndarray            # float, gathered over readable only
    cui_r: np.ndarray             # cuisine index gathered over readable
    # bookkeeping
    s_sources: int
    n_gate_levels: int            # K = max(gate_lv)+1 (>=2 so cutpoints exist)
    reviews_skipped: bool
    coords: dict[str, Any]
    venue_meta: list[dict] = field(default_factory=list)

    @property
    def n_venues(self) -> int:
        return len(self.prestige)


@dataclass
class RankingResult:
    """Structured posterior summary (matches .cma-proof/outputs/results.json)."""

    ranking: list[dict]
    diagnostics: dict
    beta_b: dict
    beta_p: dict
    channel_coverage: dict

    def to_dict(self) -> dict:
        return {
            "divergences": self.diagnostics.get("divergences"),
            "rhat_max": self.diagnostics.get("rhat_max"),
            "ess_min": self.diagnostics.get("ess_min"),
            "beta_b": self.beta_b,
            "beta_p": self.beta_p,
            "ranking": self.ranking,
            "diagnostics": self.diagnostics,
            "channel_coverage": self.channel_coverage,
        }


# ---------------------------------------------------------------------------
# prepare_model_data — PURE (numpy + stdlib only; no PyMC import)
# ---------------------------------------------------------------------------

def _index_by_slug(rows: list[dict]) -> dict[str, dict]:
    return {r.get("slug"): r for r in rows if r.get("slug")}


def _reviews_skipped(reviews: list[dict], channel_status: dict | None) -> bool:
    """The reviews channel is skipped when explicitly flagged OR when every
    venue has a None rating (REV-02 graceful skip)."""
    if channel_status and channel_status.get("status") == "skipped":
        return True
    if not reviews:
        return True
    return all(r.get("rating") is None for r in reviews)


def prepare_model_data(
    corpus: list[dict],
    reviews: list[dict],
    booking: list[dict],
    *,
    s_sources: int,
    channel_status: dict | None = None,
) -> ModelData:
    """Join the three Phase-1 input lists by slug into model arrays (PURE).

    Parameters
    ----------
    corpus : list[dict]
        build_corpus rows: venue, slug, cuisine, prestige_score, ...
    reviews : list[dict]
        enrich_reviews rows: slug, rating, review_count, log_count_z, ...
    booking : list[dict]
        classify/run_booking records (POST-Task-1 schema WITH note+deposit):
        slug, engine, channel, g_i, filled, N_slots, off_platform, note, deposit.
    s_sources : int, keyword-only
        Number of configured prestige sources (= len(config["prestige_sources"])).
        Bounds the prestige Binomial; prestige is clamped to this. NEVER hardcoded.
    channel_status : dict | None
        The reviews channel_status dict (REV-02). When status=="skipped" the
        reviews channels are dropped from the model.

    Returns
    -------
    ModelData
    """
    rev_by_slug = _index_by_slug(reviews)
    book_by_slug = _index_by_slug(booking)

    # Venue order is the corpus order (the prestige axis is the spine).
    venues = [r for r in corpus if r.get("slug")]
    n = len(venues)

    cuisines = sorted({(r.get("cuisine") or "Other") for r in venues})
    cidx = {c: i for i, c in enumerate(cuisines)}
    cuisine_idx = np.array([cidx[(r.get("cuisine") or "Other")] for r in venues], dtype=int)

    # (0) PRESTIGE — clamp to s_sources (NEVER hardcode 7/15).
    prestige = np.array(
        [min(int(r.get("prestige_score", 0) or 0), int(s_sources)) for r in venues],
        dtype=int,
    )

    # (2) GATE — ordinal level 0..4 via the 3-arg in-repo gate_level(engine, note, deposit).
    # NOT the binary g_i, and NOT the spike's single-dict gate_level(d).
    gate_lv_list: list[int] = []
    for r in venues:
        rec = book_by_slug.get(r["slug"], {})
        engine = rec.get("engine", "") or ""
        note = rec.get("note", "") or ""
        deposit = bool(rec.get("deposit", False))
        gate_lv_list.append(int(gate_level(engine, note, deposit)[0]))
    gate_lv = np.array(gate_lv_list, dtype=int)
    n_gate_levels = int(gate_lv.max()) + 1 if n else 2
    n_gate_levels = max(n_gate_levels, 2)  # need >=1 cutpoint

    # (1) REVIEWS — drop the channel entirely when skipped (REV-02).
    skipped = _reviews_skipped(reviews, channel_status)
    if skipped:
        rating = None
        n_rev = None
        logcount_z = None
    else:
        rating = np.array(
            [float(rev_by_slug.get(r["slug"], {}).get("rating") or 0.0) for r in venues],
            dtype=float,
        )
        n_rev = np.array(
            [max(int(rev_by_slug.get(r["slug"], {}).get("review_count") or 1), 1) for r in venues],
            dtype=float,
        )
        # Prefer the precomputed standardized log count (REV-03); fall back to
        # standardizing here if it is absent.
        lcz = [rev_by_slug.get(r["slug"], {}).get("log_count_z") for r in venues]
        if any(v is None for v in lcz):
            logc = np.log(n_rev)
            sd = logc.std() or 1.0
            logcount_z = (logc - logc.mean()) / sd
        else:
            logcount_z = np.array([float(v) for v in lcz], dtype=float)

    # (3) FILL — readable index = channel=="readable" AND truthy N_slots.
    # MODEL-04: blocked-here / gated venues are ABSENT here (never zero-filled).
    readable_idx: list[int] = []
    for i, r in enumerate(venues):
        rec = book_by_slug.get(r["slug"], {})
        if rec.get("channel") == "readable" and rec.get("N_slots"):
            readable_idx.append(i)
    readable = np.array(readable_idx, dtype=int)
    filled = np.array(
        [float(book_by_slug[venues[i]["slug"]]["filled"]) for i in readable_idx],
        dtype=float,
    )
    N_slots = np.array(
        [float(book_by_slug[venues[i]["slug"]]["N_slots"]) for i in readable_idx],
        dtype=float,
    )
    cui_r = cuisine_idx[readable] if len(readable) else np.array([], dtype=int)

    coords = {
        "venue": np.arange(n),
        "cuisine": cuisines,
        "readable": readable,
    }

    # venue_meta — per-venue render inputs (untouched downstream; never fabricated).
    venue_meta: list[dict] = []
    readable_set = set(readable_idx)
    for i, r in enumerate(venues):
        rec = book_by_slug.get(r["slug"], {})
        rv = rev_by_slug.get(r["slug"], {})
        is_readable = i in readable_set
        fill = None
        if is_readable and rec.get("N_slots"):
            fill = float(rec["filled"]) / float(rec["N_slots"])
        venue_meta.append({
            "venue": r.get("venue", r["slug"]),
            "slug": r["slug"],
            "cuisine": r.get("cuisine") or "Other",
            "prestige_score": int(r.get("prestige_score", 0) or 0),
            "s_sources": int(s_sources),
            "michelin": r.get("michelin"),   # corpus emits none -> None (A2)
            "rating": rv.get("rating") if not skipped else None,
            "n_reviews": rv.get("review_count") if not skipped else None,
            "gate_lv": int(gate_lv[i]),
            "gate_label": gate_level(rec.get("engine", "") or "",
                                     rec.get("note", "") or "",
                                     bool(rec.get("deposit", False)))[1],
            "readable": is_readable,
            "fill": fill,
            "N_slots": rec.get("N_slots"),
            "engine": rec.get("engine"),
            "off_platform": bool(rec.get("off_platform", False)),
        })

    return ModelData(
        prestige=prestige,
        gate_lv=gate_lv,
        cuisine_idx=cuisine_idx,
        rating=rating,
        n_rev=n_rev,
        logcount_z=logcount_z,
        readable=readable,
        N_slots=N_slots,
        filled=filled,
        cui_r=cui_r,
        s_sources=int(s_sources),
        n_gate_levels=n_gate_levels,
        reviews_skipped=skipped,
        coords=coords,
        venue_meta=venue_meta,
    )


# ---------------------------------------------------------------------------
# build_model — PURE construct (PyMC imported INSIDE this function only)
# ---------------------------------------------------------------------------

def build_model(md: ModelData):
    """Construct the frozen spike-022 4-channel PyMC model (no sampling).

    Ports model_prestige.py lines 43-65 VERBATIM in its math. Identification
    anchors are load-bearing and UNCHANGED: sigma_q=1, mu0=0, beta_r>0, beta_p>0,
    gamma=1 (unit-coef -log_cap offset), kappa0=0, log_cap over READABLE only.

    When md.reviews_skipped, the rating_obs/count_obs channels are omitted (REV-02).
    """
    import pymc as pm  # heavy dep — imported only when the model is actually built

    coords = md.coords
    cuisine_idx = md.cuisine_idx
    K = md.n_gate_levels

    with pm.Model(coords=coords) as model:
        tau = pm.HalfNormal("tau", 0.3)
        mc = pm.Deterministic(
            "mu_c", tau * pm.Normal("mu_c_off", 0, 1, dims="cuisine"), dims="cuisine"
        )
        ql = pm.Deterministic(
            "q", mc[cuisine_idx] + pm.Normal("q_off", 0, 1, dims="venue"), dims="venue"
        )

        # (0) PRESTIGE — editorial reputation; beta_p>0 anchors q's sign/scale.
        ap = pm.Normal("alpha_p", -1, 1)
        bp = pm.HalfNormal("beta_p", 1.5)
        pm.Binomial(
            "prestige_obs", n=md.s_sources, logit_p=ap + bp * ql,
            observed=md.prestige, dims="venue",
        )

        # (1) REVIEWS — rating w/ sigma0 floor + standardized log-count channel.
        if not md.reviews_skipped:
            n_rev = pm.Data("n_rev", md.n_rev, dims="venue")
            ar = pm.Normal("alpha_r", 4.5, 0.5)
            br = pm.HalfNormal("beta_r", 1)
            sr = pm.HalfNormal("sigma_r", 0.5)
            s0 = pm.HalfNormal("sigma0", 0.1)
            pm.Normal(
                "rating_obs", ar + br * ql,
                pm.math.sqrt(sr ** 2 / n_rev + s0 ** 2),
                observed=md.rating, dims="venue",
            )
            ac = pm.Normal("alpha_c", 0, 1)
            bc = pm.HalfNormal("beta_c", 1)
            scc = pm.HalfNormal("sigma_c", 1)
            pm.Normal("count_obs", ac + bc * ql, scc, observed=md.logcount_z, dims="venue")

        # (2) GATE — ORDINAL ladder; OrderedLogistic => default NUTS (nutpie can't do `ordered`).
        bgl = pm.HalfNormal("beta_gl", 2)
        cps = pm.Normal(
            "cut", 0, 2, shape=K - 1,
            transform=pm.distributions.transforms.ordered,
            initval=np.linspace(-2, 2, K - 1),
        )
        pm.OrderedLogistic("gate_obs", eta=bgl * ql, cutpoints=cps,
                           observed=md.gate_lv, dims="venue")

        # (3) FILL — readable venues only; latent capacity; gamma=1, kappa0=0 anchors.
        if len(md.readable):
            sc = pm.HalfNormal("sigma_cap", 0.5)
            kp = pm.Deterministic(
                "kappa", 0.5 * pm.Normal("kappa_off", 0, 1, dims="cuisine"), dims="cuisine"
            )
            lcr = pm.Deterministic(
                "log_cap_r",
                kp[md.cui_r] + sc * pm.Normal("logcap_off", 0, 1, dims="readable"),
                dims="readable",
            )
            ab = pm.Normal("alpha_b", 0, 1.5)
            bb = pm.Normal("beta_b", 0, 1)
            pm.Binomial(
                "fill_obs", n=md.N_slots, logit_p=ab + bb * ql[md.readable] - lcr,
                observed=md.filled, dims="readable",
            )

    return model


# ---------------------------------------------------------------------------
# fit — THE sampling seam (the ONLY function that calls pm.sample)
# ---------------------------------------------------------------------------

def fit(model, *, seed: int = 42, draws: int = 1500, tune: int = 3000,
        target_accept: float = 0.97, save_path: str | os.PathLike | None = None):
    """Run NUTS and return the InferenceData. The slow/non-deterministic seam.

    Default NUTS (NOT nutpie — it cannot do the `ordered` transform on the gate
    cutpoints, Pitfall 3). Saves the idata early (try/except) so re-render does
    not re-sample (mirrors spike-014).
    """
    import pymc as pm

    with model:
        idata = pm.sample(
            draws=draws, tune=tune, chains=4,
            target_accept=target_accept, random_seed=seed, progressbar=False,
        )

    if save_path is not None:
        try:
            idata.to_netcdf(str(save_path), engine="h5netcdf")
        except Exception:
            pass  # save-early is best-effort; never fail the fit on a save error

    return idata


# ---------------------------------------------------------------------------
# summarize_posterior — PURE (arviz imported inside; testable on a mocked idata)
# ---------------------------------------------------------------------------

def summarize_posterior(idata, venue_meta: list[dict]) -> RankingResult:
    """InferenceData -> RankingResult (ranked records + diagnostics). PURE.

    Uses az.hdi(..., prob=0.94) — arviz 1.x API (NOT hdi_prob=, Pitfall 1).
    Each record's readable/fill/Nslots/engine/off_platform come straight from
    venue_meta — never fabricated (MODEL-04 honesty).
    """
    import arviz as az

    post = idata.posterior

    # Diagnostics (MODEL-03).
    try:
        n_div = int(idata.sample_stats["diverging"].sum())
    except Exception:
        n_div = 0
    diag_vars = [v for v in ("beta_p", "beta_b", "beta_r", "tau", "sigma_cap")
                 if v in post]
    rhat_max = None
    ess_min = None
    if diag_vars:
        summ = az.summary(idata, var_names=diag_vars)
        if "r_hat" in summ:
            rhat_max = float(summ["r_hat"].max())
        if "ess_bulk" in summ:
            ess_min = float(summ["ess_bulk"].min())

    q_mean = post["q"].mean(("chain", "draw")).values
    hdi = az.hdi(idata, var_names=["q"], prob=0.94)["q"].values  # 1.x: prob=, not hdi_prob=

    # beta_b / beta_p summaries.
    def _beta_summary(name: str, want_p: bool) -> dict | None:
        if name not in post:
            return None
        vals = post[name].values
        h = az.hdi(idata, var_names=[name], prob=0.94)[name].values
        d = {
            "mean": float(vals.mean()),
            "sd": float(vals.std()),
            "hdi": [float(h[0]), float(h[1])],
        }
        if want_p:
            d["p_gt0"] = float((vals > 0).mean())
        return d

    beta_b = _beta_summary("beta_b", want_p=True) or {
        "mean": None, "sd": None, "p_gt0": None, "hdi": [None, None],
    }
    beta_p = _beta_summary("beta_p", want_p=False) or {
        "mean": None, "sd": None, "hdi": [None, None],
    }

    order = np.argsort(-q_mean)
    ranking: list[dict] = []
    for rank, i in enumerate(order, start=1):
        meta = venue_meta[i] if i < len(venue_meta) else {}
        ranking.append({
            "rank": rank,
            "name": meta.get("venue"),
            "cuisine": meta.get("cuisine"),
            "michelin": meta.get("michelin"),  # None for current corpus (A2)
            "prestige": meta.get("prestige_score"),
            "rating": meta.get("rating"),
            "n": meta.get("n_reviews"),
            "gate": meta.get("gate_lv"),
            "readable": meta.get("readable"),
            "fill": meta.get("fill"),
            "Nslots": meta.get("N_slots"),
            "engine": meta.get("engine"),
            "q": float(q_mean[i]),
            "hdi_lo": float(hdi[i, 0]),
            "hdi_hi": float(hdi[i, 1]),
        })

    n_readable = sum(1 for m in venue_meta if m.get("readable"))
    channel_coverage = {
        "readable": n_readable,
        "total": len(venue_meta),
        "reviews_status": "skipped" if all(m.get("rating") is None for m in venue_meta)
                          and venue_meta else "ok",
    }

    # chains/draws for the diagnostics block.
    try:
        chains = int(post.sizes["chain"])
        draws = int(post.sizes["draw"])
    except Exception:
        chains = draws = None

    diagnostics = {
        "divergences": n_div,
        "rhat_max": rhat_max,
        "ess_min": ess_min,
        "sampler": "NUTS",
        "chains": chains,
        "draws": draws,
    }

    return RankingResult(
        ranking=ranking,
        diagnostics=diagnostics,
        beta_b=beta_b,
        beta_p=beta_p,
        channel_coverage=channel_coverage,
    )


# ---------------------------------------------------------------------------
# main — CLI (output-to-CWD; S_SOURCES from the city config; no hardcode)
# ---------------------------------------------------------------------------

def _load_json_list(path: str, label: str) -> list:
    """json.load a list-of-dicts input with an actionable error (V5 / T-02-02)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load {label} '{path}': {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{label} '{path}' must be a JSON array, got {type(data).__name__}")
    return data


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="model.py",
        description=(
            "Fit the 4-channel hierarchical latent-quality model for a city and "
            "write a structured ranking (results.json + the posterior .nc) to CWD."
        ),
    )
    p.add_argument("--city", required=True, help="City name or slug (e.g. 'manila').")
    p.add_argument("--corpus", required=True, help="Path to <slug>-corpus.json.")
    p.add_argument("--reviews", required=True, help="Path to <slug>-reviews.json.")
    p.add_argument("--booking", required=True, help="Path to <slug>-booking.json.")
    p.add_argument("--out", default=None, help="Output results.json path (default CWD).")
    p.add_argument("--draws", type=int, default=1500)
    p.add_argument("--tune", type=int, default=3000)
    p.add_argument("--seed", type=int, default=42)
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = _build_parser().parse_args(argv)

    # Load city config; derive S_SOURCES from len(prestige_sources) — NO hardcode (Q2).
    try:
        config = load_city(args.city)
    except (UnknownCityError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    s_sources = len(config.get("prestige_sources", []))
    if s_sources <= 0:
        print("ERROR: city config has no prestige_sources", file=sys.stderr)
        return 1

    # Slugify the city slug to [a-z0-9-] before any path-join (T-02-01).
    # cityconfig already produced a safe slug via _slugify; reuse it directly.
    slug = config["slug"]

    try:
        corpus = _load_json_list(args.corpus, "corpus")
        reviews = _load_json_list(args.reviews, "reviews")
        booking = _load_json_list(args.booking, "booking")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    md = prepare_model_data(corpus, reviews, booking, s_sources=s_sources)

    out_path = Path(args.out) if args.out else Path(os.getcwd()) / f"{slug}-results.json"
    nc_path = Path(os.getcwd()) / f"{slug}-posterior.nc"

    model = build_model(md)
    idata = fit(model, seed=args.seed, draws=args.draws, tune=args.tune, save_path=nc_path)
    result = summarize_posterior(idata, md.venue_meta)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, indent=2, ensure_ascii=False)

    cov = result.channel_coverage
    print(f"city:        {config['city']}")
    print(f"S_SOURCES:   {s_sources} (from len(prestige_sources))")
    print(f"venues:      {md.n_venues} ({cov['readable']}/{cov['total']} readable)")
    print(f"divergences: {result.diagnostics['divergences']}")
    print(f"output:      {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
