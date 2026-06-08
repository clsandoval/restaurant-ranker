"""render.py — render a RankingResult into a plain-markdown board + results.json.

PURE STDLIB. This module consumes the ALREADY-SUMMARIZED posterior (a
``RankingResult`` of plain dicts/lists produced by ``model.summarize_posterior``)
and produces a plain-markdown "board" string reproducing the verified
iter3 board shape, plus a structured ``<slug>-results.json``
sidecar. Both are written to the caller's CWD.

IMPORT DISCIPLINE (load-bearing): render.py imports NOTHING heavy — no pymc,
no arviz, no numpy. It works on the summarized result, not an InferenceData,
so the whole module + its tests run on a PyMC-less system interpreter. The only
non-stdlib coupling is the in-repo ``cityconfig.load_city`` (used by ``main``
to derive the safe slug + S_SOURCES — never a hardcode).

SEAM DISCIPLINE: ``render_board`` is a PURE str-producing function (no file I/O).
``main`` is the ONLY thing that touches the filesystem, and it writes under
``Path(os.getcwd())`` with a slugified name (T-02-01) — no hardcoded paths.

HONESTY RAIL (RENDER-03): a venue with no fill observation renders an em-dash
``—`` and keeps its (visibly wide) HDI. A fabricated/zeroed confidence number is
NEVER substituted. ``fill == 0.0`` is a REAL observation (a wide-open calendar)
and renders ``0.00`` — only ``fill is None`` (absent channel) renders ``—``.

A2 / Open Question 1 (RESOLVED): the current corpus emits NO ``michelin`` field,
so every live venue has ``michelin = None`` and the prestige cell degrades to
``<prestige>/<S>``. The michelin-star branch is FORWARD-COMPAT ONLY (inert for
the present corpus) — kept and pinned by tests so a future corpus enrichment
lights it up without a render change.

Python 3.10 stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Resolve the sibling cityconfig module (slug + S_SOURCES) — same __file__-relative
# sys.path pattern booking.py / model.py use. Imported only for main().
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

__all__ = [
    "RankingResult",
    "GATE_LABELS",
    "MICHELIN_STARS",
    "gate_label",
    "fill_cell",
    "qbar_cell",
    "michelin_stars",
    "prestige_cell",
    "render_board",
    "main",
]


# ---------------------------------------------------------------------------
# Light RankingResult — decoupled from model.py's numpy-bearing dataclass so the
# render path needs no numpy. Reconstructed straight from the results.json dict.
# ---------------------------------------------------------------------------

@dataclass
class RankingResult:
    """Plain-stdlib mirror of model.RankingResult (no numpy)."""

    ranking: list[dict]
    diagnostics: dict
    beta_b: dict
    beta_p: dict
    channel_coverage: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "RankingResult":
        """Reconstruct from a model.py-emitted results.json dict.

        Tolerates the two top-level shapes model.py emits: the nested
        ``diagnostics`` block, plus the flattened ``divergences/rhat_max/ess_min``
        convenience keys. Prefers the nested block, falling back to the flat keys.
        """
        diag = dict(d.get("diagnostics") or {})
        # Backfill from flat top-level keys when the nested block omits them.
        for k in ("divergences", "rhat_max", "ess_min"):
            diag.setdefault(k, d.get(k))
        diag.setdefault("sampler", diag.get("sampler", "NUTS"))
        diag.setdefault("chains", diag.get("chains"))
        diag.setdefault("draws", diag.get("draws"))
        return cls(
            ranking=list(d.get("ranking") or []),
            diagnostics=diag,
            beta_b=dict(d.get("beta_b") or {}),
            beta_p=dict(d.get("beta_p") or {}),
            channel_coverage=dict(d.get("channel_coverage") or {}),
        )

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
# Label maps + cell helpers (all PURE).
# ---------------------------------------------------------------------------

# Ordinal gate level 0..4 -> the 3-label collapse the cma-proof board uses.
#   0 online / 1 walk-in   -> "online"     (no friction wall)
#   2 phone-IG / deposit?  -> "prepay/hard" (hard reservation friction)
#   3 deposit / 4 lottery  -> "ticket-drop" (timed-release / hardest)
GATE_LABELS: dict[int, str] = {
    0: "online",
    1: "online",
    2: "prepay/hard",
    3: "ticket-drop",
    4: "ticket-drop",
}

# Forward-compat michelin tier -> star/badge prefix (INERT for current corpus).
MICHELIN_STARS: dict[str, str] = {
    "3-star": "★★★",
    "2-star": "★★",
    "1-star": "★",
    "bib": "Bib",
}

# Coverage identifiability floor (the ~10-venue threshold from the brief).
_COVERAGE_FLOOR = 10

_NO_MICHELIN = {None, "", "none", "None"}


def gate_label(level: Any) -> str:
    """Map an ordinal gate level (0..4) to the collapsed board label."""
    try:
        lv = int(level)
    except (TypeError, ValueError):
        return "online"
    return GATE_LABELS.get(lv, "prepay/hard")


def fill_cell(fill: Any) -> str:
    """Format the fill cell. None -> em-dash (absent channel, RENDER-03);
    a real value (including 0.0, a wide-open calendar) -> 2dp fraction."""
    if fill is None:
        return "—"
    return f"{float(fill):.2f}"


def qbar_cell(q: float, lo: float, hi: float) -> str:
    """Format the q̄ + 94% HDI cell: '+2.23 [+1.07, +3.43]' (signed, 2dp)."""
    return f"{float(q):+.2f} [{float(lo):+.2f}, {float(hi):+.2f}]"


def michelin_stars(michelin: Any) -> str | None:
    """Return the star/badge prefix for a michelin tier, or None when absent.

    Forward-compat ONLY — the current corpus always passes None/'none'.
    """
    if michelin in _NO_MICHELIN:
        return None
    return MICHELIN_STARS.get(str(michelin))


def prestige_cell(michelin: Any, prestige: Any, s_sources: Any) -> str:
    """Render the prestige cell.

    LIVE path (current corpus): michelin is None -> '<prestige>/<S>' (e.g. '13/15').
    Forward-compat branch (inert): michelin set -> '★★★ · 13/15'.
    """
    base = f"{int(prestige)}/{int(s_sources)}"
    stars = michelin_stars(michelin)
    if stars is None:
        return base
    return f"{stars} · {base}"


# ---------------------------------------------------------------------------
# Small formatting utilities for the diagnostics block.
# ---------------------------------------------------------------------------

def _fmt_num(x: Any, fmt: str = "{:.4f}", default: str = "n/a") -> str:
    if x is None:
        return default
    try:
        return fmt.format(float(x))
    except (TypeError, ValueError):
        return str(x)


def _fmt_int(x: Any, default: str = "n/a") -> str:
    if x is None:
        return default
    try:
        return str(int(round(float(x))))
    except (TypeError, ValueError):
        return str(x)


def _reviews_status_str(coverage: dict) -> str:
    return str(coverage.get("reviews_status") or "ok")


# ---------------------------------------------------------------------------
# render_board — PURE str -> str. NO file I/O.
# ---------------------------------------------------------------------------

def render_board(result: RankingResult, run_meta: dict) -> str:
    """Render a RankingResult into the 4-section plain-markdown board (PURE).

    Reproduces the verified iter3 board shape:
      Header / §1 FILL EVIDENCE / §2 TOP-N BOARD / §3 Honesty note /
      §4 Did live booking demand move the ranking?

    No file is opened or written here — this is a pure string builder.
    """
    ranking = list(result.ranking)
    diag = result.diagnostics or {}
    coverage = result.channel_coverage or {}

    plugin = run_meta.get("plugin", "lakbai")
    city = run_meta.get("city") or run_meta.get("slug") or "city"
    s_sources = run_meta.get("s_sources")
    if s_sources is None:
        # Derive S from the widest prestige seen if run_meta omits it.
        s_sources = max((int(r.get("prestige") or 0) for r in ranking), default=0)

    n_total = coverage.get("total", len(ranking))
    n_readable = coverage.get(
        "readable", sum(1 for r in ranking if r.get("readable"))
    )
    reviews_status = _reviews_status_str(coverage)
    reviews_skipped = reviews_status == "skipped"

    # Board is rendered by descending q (defensive — input may already be sorted).
    board_rows = sorted(ranking, key=lambda r: r.get("q", 0.0), reverse=True)

    lines: list[str] = []

    # --- Header -----------------------------------------------------------
    lines.append(f"# {plugin} · {city} restaurant ranking")
    lines.append("")
    lines.append(
        "*Bayesian 4-channel model (prestige + reviews + gate + LIVE fill), "
        "partial-pooled by cuisine. Read-only throughout — calendars were read, "
        "never booked.*"
    )
    lines.append("")
    reviews_hdr = "skipped (no API key)" if reviews_skipped else reviews_status
    lines.append(
        f"**Corpus:** {n_total} venues · **prestige sources S={s_sources}** · "
        f"**reviews** {reviews_hdr} · "
        f"**{n_readable} venues read LIVE for booking-fill.**"
    )
    lines.append("")
    lines.append("---")

    # --- §1 FILL EVIDENCE -------------------------------------------------
    lines.append("## 1 · FILL EVIDENCE — live booking-calendar reads")
    lines.append("")
    lines.append(
        "Each readable venue's booking engine was discovered from scratch and its "
        "live availability read read-only. `fill = Σ filled / (grid × dates)` — "
        "higher = harder to get a table."
    )
    lines.append("")
    lines.append("| venue | engine | live read | N | **fill** |")
    lines.append("|---|---|--:|--:|--:|")
    readable_rows = [r for r in board_rows if r.get("readable")]
    readable_rows.sort(key=lambda r: (r.get("fill") or 0.0), reverse=True)
    for r in readable_rows:
        engine = r.get("engine") or "—"
        nslots = r.get("Nslots")
        nstr = _fmt_int(nslots, default="—")
        live = "live read" if r.get("fill") is not None else "—"
        lines.append(
            f"| **{r.get('name')}** | {engine} | {live} | {nstr} | "
            f"**{fill_cell(r.get('fill'))}** |"
        )
    cleared = n_readable >= _COVERAGE_FLOOR
    floor_note = (
        f"well above the ~{_COVERAGE_FLOOR}-venue identifiability floor — floor "
        f"cleared, so fill enters the model (β_b)"
        if cleared
        else f"below the ~{_COVERAGE_FLOOR}-venue identifiability floor — fill is "
        f"reported but the floor was not cleared"
    )
    lines.append("")
    lines.append(f"*Coverage: {n_readable}/{n_total} venues read live — {floor_note}.*")
    lines.append("")
    lines.append("---")

    # --- §2 TOP-N BOARD ---------------------------------------------------
    lines.append(f"## 2 · TOP-{len(board_rows)} BOARD")
    lines.append("")
    lines.append(
        "| # | venue | cuisine | prestige | rating (n) | gate | fill | q̄ (94% HDI) |"
    )
    lines.append("|--:|---|---|--:|---|---|--:|---|")
    for r in board_rows:
        rating = r.get("rating")
        n = r.get("n")
        if rating is None:
            rating_cell = "—"
        elif n is None:
            rating_cell = f"{float(rating):.1f}"
        else:
            rating_cell = f"{float(rating):.1f} ({_fmt_int(n)})"
        lines.append(
            "| {rank} | **{name}** | {cuisine} | {prestige} | {rating} | "
            "{gate} | {fill} | {q} |".format(
                rank=r.get("rank", ""),
                name=r.get("name"),
                cuisine=r.get("cuisine") or "—",
                prestige=prestige_cell(r.get("michelin"), r.get("prestige") or 0, s_sources),
                rating=rating_cell,
                gate=gate_label(r.get("gate")),
                fill=fill_cell(r.get("fill")),
                q=qbar_cell(r.get("q", 0.0), r.get("hdi_lo", 0.0), r.get("hdi_hi", 0.0)),
            )
        )
    lines.append("")
    lines.append(
        "*Full board in `results.json`. gate: online · prepay/hard · ticket-drop.*"
    )
    lines.append("")
    lines.append("---")

    # --- §3 Honesty note --------------------------------------------------
    lines.append("## 3 · Honesty note")
    lines.append("")
    chains = diag.get("chains")
    draws = diag.get("draws")
    cxd = (
        f"{_fmt_int(chains)} chains × {_fmt_int(draws)} draws"
        if chains is not None or draws is not None
        else "chains × draws n/a"
    )
    lines.append(
        f"- **Convergence:** {_fmt_int(diag.get('divergences'))} divergences, "
        f"max r̂ = {_fmt_num(diag.get('rhat_max'))}, "
        f"min ESS ≈ {_fmt_int(diag.get('ess_min'))} across {cxd} "
        f"({diag.get('sampler', 'NUTS')})."
    )
    floor_phrase = "cleared" if cleared else "not cleared"
    lines.append(
        f"- **Fill coverage:** {n_readable}/{n_total} venues read live "
        f"(~{_COVERAGE_FLOOR}-venue floor {floor_phrase})."
    )
    lines.append(
        "- **Uncertainty is real:** 94% HDIs on q are wide and overlap across the "
        "gated fine-dining tier — the board renders that overlap rather than faking "
        "a confident ordering. Off-platform venues show `—` for fill and keep their "
        "wide interval; no fabricated confidence."
    )
    lines.append(
        "- **Provenance:** prestige sets the tiers; live booking demand reorders "
        "*within* a tier, it does not manufacture quality."
    )
    if reviews_skipped:
        lines.append(
            "- **reviews: skipped** — the reviews channel was skipped (no API key); "
            "rating columns degrade to `—` and the model dropped the rating/count "
            "channels (REV-02)."
        )
    lines.append("")

    # --- §4 Did live booking demand move the ranking? ---------------------
    lines.append("## 4 · Did live booking demand move the ranking?")
    lines.append("")
    bb = result.beta_b or {}
    bp = result.beta_p or {}
    bb_mean = bb.get("mean")
    bb_hdi = bb.get("hdi") or [None, None]
    bb_p = bb.get("p_gt0")
    moved = bb_mean is not None and float(bb_mean) > 0
    verdict = "**Yes.**" if moved else "**Inconclusive.**"
    lines.append(
        f"{verdict} The fill slope **β_b = {_fmt_num(bb_mean, '{:.2f}')}** "
        f"(94% HDI [{_fmt_num(bb_hdi[0], '{:.2f}')}, "
        f"{_fmt_num(bb_hdi[1], '{:.2f}')}], "
        f"P(β_b>0) = {_fmt_num(bb_p, '{:.2f}')}) — booked-solid calendars load "
        f"onto higher latent quality."
    )
    bp_mean = bp.get("mean")
    bp_hdi = bp.get("hdi") or [None, None]
    lines.append("")
    lines.append(
        f"(Prestige slope β_p = {_fmt_num(bp_mean, '{:.2f}')}, "
        f"HDI [{_fmt_num(bp_hdi[0], '{:.2f}')}, {_fmt_num(bp_hdi[1], '{:.2f}')}] "
        f"for context.)"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main — CLI (the ONLY filesystem seam). Writes board.md + results.json to CWD.
# ---------------------------------------------------------------------------

def _load_results(path: str) -> dict:
    """json.load the results input with an actionable error (V5 / T-02-02)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load results '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"results '{path}' must be a JSON object (the RankingResult dict), "
            f"got {type(data).__name__}"
        )
    if "ranking" not in data:
        raise ValueError(
            f"results '{path}' has no 'ranking' key — is this a model.py results.json?"
        )
    return data


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="render.py",
        description=(
            "Render a model.py RankingResult (results.json) into a plain-markdown "
            "board + a results.json sidecar, written to CWD. PURE STDLIB — no PyMC."
        ),
    )
    p.add_argument("--city", required=True, help="City name or slug (e.g. 'manila').")
    p.add_argument(
        "--results",
        required=True,
        help="Path to the model.py-emitted results.json (the RankingResult dict).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output board.md path. Defaults to <cwd>/<slug>-board.md.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = _build_parser().parse_args(argv)

    # cityconfig is imported here (not at module top) to keep the import-light
    # guarantee tight: render_board itself needs nothing but stdlib.
    from cityconfig import load_city, UnknownCityError  # noqa: E402

    # Load city config — derive the safe slug + S_SOURCES (no hardcode).
    try:
        config = load_city(args.city)
    except (UnknownCityError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # cityconfig._slugify already produced a [a-z0-9-] slug (T-02-01) — reuse it.
    slug = config["slug"]
    s_sources = len(config.get("prestige_sources", []))

    try:
        data = _load_results(args.results)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    result = RankingResult.from_dict(data)
    run_meta = {
        "city": config.get("city", slug),
        "slug": slug,
        "s_sources": s_sources,
        "plugin": "lakbai",
    }
    board_md = render_board(result, run_meta)

    # Resolve output paths under CWD — no hardcoded paths (RENDER-05).
    board_path = Path(args.out) if args.out else Path(os.getcwd()) / f"{slug}-board.md"
    results_path = Path(os.getcwd()) / f"{slug}-results.json"

    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(board_md, encoding="utf-8")

    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, indent=2, ensure_ascii=False)

    cov = result.channel_coverage or {}
    print(f"city:    {config.get('city', slug)}")
    print(f"venues:  {cov.get('total', len(result.ranking))} "
          f"({cov.get('readable', 0)} read live)")
    print(f"board:   {board_path}")
    print(f"results: {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
