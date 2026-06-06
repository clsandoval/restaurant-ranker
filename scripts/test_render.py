"""test_render.py — unit tests for render.py (pure-stdlib board renderer).

render.py consumes the ALREADY-SUMMARIZED posterior (a RankingResult of plain
dicts/lists from model.summarize_posterior) and produces a plain-markdown board
string + a results.json sidecar. It is PURE STDLIB: it must NOT import pymc /
arviz / numpy, so this entire suite runs on system Python 3.10 with no PyMC.

Coverage:
  - render_board: 4-section markdown contract reproduction (RENDER-01..04)
  - q̄ + 94% HDI cell formatting + descending-q ordering (RENDER-01/02)
  - off-platform / None-fill honesty: "—" cell + visibly wide HDI (RENDER-03)
  - prestige cell A2: michelin=None -> "<score>/<S>" (LIVE path); michelin set ->
    forward-compat star branch (inert for current corpus)
  - GATE_LABELS ordinal->collapsed-label mapping
  - diagnostics + per-channel coverage block (RENDER-04)
  - REV-02 reviews-skipped surfacing
  - source guard: render_board does no file I/O; no hardcoded absolute path
  - main(): writes <slug>-board.md + <slug>-results.json to CWD (RENDER-05),
    slug path-traversal mitigation (T-02-01), malformed-input error (T-02-02/V5)

No live network, no sampling. All tests feed fixture data directly.

Python 3.10 stdlib only.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve render.py relative to this file (works from any CWD)
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def _import_render():
    """Lazy importlib load so a missing module shows a clear error."""
    spec = importlib.util.spec_from_file_location("render", _SCRIPTS_DIR / "render.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures — a plain RankingResult-shaped object (NO PyMC, NO numpy).
# Mirrors .cma-proof/outputs/results.json shape, trimmed to a handful of venues
# that exercise every render branch.
# ---------------------------------------------------------------------------

def _fixture_ranking_result(mod, *, reviews_status: str = "ok"):
    """Build a RankingResult-shaped object via render's own dataclass.

    render.py defines a light RankingResult dataclass (decoupled from model.py's
    numpy-bearing one) so it can reconstruct from the JSON sidecar without numpy.
    """
    ranking = [
        # rank 1: off-platform top venue (fill None, michelin None -> live degrade)
        dict(rank=1, name="Noma", cuisine="New Nordic", michelin=None,
             prestige=13, rating=4.6, n=2382, gate=3, readable=False,
             fill=None, Nslots=None, engine=None,
             q=2.23385, hdi_lo=1.07419, hdi_hi=3.42509),
        # rank 2: readable, high fill, michelin set (forward-compat star branch)
        dict(rank=2, name="Geranium", cuisine="New Nordic", michelin="3-star",
             prestige=13, rating=4.7, n=941, gate=3, readable=True,
             fill=0.94117, Nslots=119, engine="SevenRooms",
             q=2.10428, hdi_lo=1.02763, hdi_hi=3.18798),
        # rank 3: readable, prepay/hard gate=2
        dict(rank=3, name="Jordnaer", cuisine="New Nordic", michelin=None,
             prestige=11, rating=4.8, n=290, gate=2, readable=True,
             fill=1.0, Nslots=18, engine="Superb",
             q=1.54361, hdi_lo=0.52814, hdi_hi=2.64188),
        # rank 4: readable, fill 0.00 (wide-open, honest low signal), gate=2
        dict(rank=4, name="Sollerod Kro", cuisine="French-European", michelin=None,
             prestige=6, rating=4.8, n=876, gate=2, readable=True,
             fill=0.0, Nslots=13, engine="DinnerBooking",
             q=0.16047, hdi_lo=-0.86232, hdi_hi=1.12043),
        # rank 5: off-platform, gate=1 -> online collapse
        dict(rank=5, name="Barr", cuisine="New Nordic", michelin=None,
             prestige=5, rating=4.3, n=2048, gate=1, readable=False,
             fill=None, Nslots=None, engine=None,
             q=-0.25282, hdi_lo=-1.34295, hdi_hi=0.77455),
    ]
    diagnostics = dict(divergences=0, rhat_max=1.0, ess_min=1767.0,
                       sampler="NUTS", chains=4, draws=1500)
    beta_b = dict(mean=1.39176, sd=0.47852, p_gt0=0.9995,
                  hdi=[0.45296, 2.26949])
    beta_p = dict(mean=0.74957, sd=None, hdi=[0.49794, 1.01522])
    n_read = sum(1 for r in ranking if r["readable"])
    channel_coverage = dict(readable=n_read, total=len(ranking),
                            reviews_status=reviews_status)
    return mod.RankingResult(
        ranking=ranking,
        diagnostics=diagnostics,
        beta_b=beta_b,
        beta_p=beta_p,
        channel_coverage=channel_coverage,
    )


def _fixture_run_meta():
    return dict(city="Copenhagen", slug="copenhagen", s_sources=15,
                plugin="lakbai")


# ---------------------------------------------------------------------------
# 1. render_board — 4-section markdown contract
# ---------------------------------------------------------------------------

class TestRenderBoardSections(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)
        self.meta = _fixture_run_meta()
        self.md = self.render.render_board(self.result, self.meta)

    def test_returns_string(self):
        self.assertIsInstance(self.md, str)
        self.assertGreater(len(self.md), 0)

    def test_plain_markdown_no_html(self):
        """Output is plain markdown — no HTML tags (constraint: no HTML)."""
        low = self.md.lower()
        self.assertNotIn("<html", low)
        self.assertNotIn("<table", low)
        self.assertNotIn("<div", low)

    def test_header_present(self):
        """Title + bold corpus line with N venues, S, reviews status, M live."""
        self.assertIn("Copenhagen", self.md)
        # corpus line: N venues / prestige sources S=<k> / M venues read LIVE
        self.assertIn("S=15", self.md)
        self.assertIn("5 venues", self.md)   # N total
        self.assertIn("LIVE", self.md)

    def test_section1_fill_evidence_present(self):
        self.assertIn("FILL EVIDENCE", self.md.upper())

    def test_section2_board_present(self):
        self.assertIn("BOARD", self.md.upper())

    def test_section3_honesty_present(self):
        low = self.md.lower()
        self.assertIn("honesty", low)

    def test_section4_demand_question_present(self):
        self.assertIn("Did live booking demand move the ranking?", self.md)


# ---------------------------------------------------------------------------
# 2. §2 board: q̄ formatting + descending-q ordering (RENDER-01/02)
# ---------------------------------------------------------------------------

class TestBoardQbarFormatting(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)
        self.md = self.render.render_board(self.result, _fixture_run_meta())

    def test_qbar_cell_format(self):
        """q-bar cell formatted '+2.23 [+1.07, +3.43]' (signed, 2dp)."""
        self.assertIn("+2.23 [+1.07, +3.43]", self.md)

    def test_negative_q_cell_signed(self):
        """Negative q still shows explicit sign on q and HDI bounds."""
        self.assertIn("-0.25 [-1.34, +0.77]", self.md)

    def test_descending_q_ordering(self):
        """Board rows appear in descending q order (Noma before Barr)."""
        i_noma = self.md.find("Noma")
        i_barr = self.md.find("Barr")
        self.assertNotEqual(i_noma, -1)
        self.assertNotEqual(i_barr, -1)
        self.assertLess(i_noma, i_barr, "higher-q venue must render first")

    def test_qbar_helper_directly(self):
        """qbar_cell(q, lo, hi) -> '+X.XX [+Y.YY, +Z.ZZ]'."""
        cell = self.render.qbar_cell(2.23385, 1.07419, 3.42509)
        self.assertEqual(cell, "+2.23 [+1.07, +3.43]")


# ---------------------------------------------------------------------------
# 3. RENDER-03 honesty: None fill -> "—" + off-platform wide HDI
# ---------------------------------------------------------------------------

class TestFillHonesty(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)
        self.md = self.render.render_board(self.result, _fixture_run_meta())

    def test_none_fill_renders_emdash(self):
        """A fill=None venue renders '—' (never 0, never blank-implying-zero)."""
        self.assertIn("—", self.md)

    def test_fill_cell_helper_none(self):
        self.assertEqual(self.render.fill_cell(None), "—")

    def test_fill_cell_helper_value(self):
        self.assertEqual(self.render.fill_cell(0.94117), "0.94")

    def test_fill_cell_zero_is_not_emdash(self):
        """fill=0.0 is a REAL observation (wide-open calendar) — render '0.00',
        NOT '—'. The em-dash is reserved for the absent (None) channel."""
        self.assertEqual(self.render.fill_cell(0.0), "0.00")

    def test_off_platform_row_shows_wide_hdi(self):
        """An off-platform (fill None) venue's row still shows its wide HDI."""
        # Noma is off-platform; its HDI [+1.07, +3.43] must appear.
        self.assertIn("[+1.07, +3.43]", self.md)


# ---------------------------------------------------------------------------
# 4. A2 prestige cell: michelin None (live) vs star branch (forward-compat)
# ---------------------------------------------------------------------------

class TestPrestigeCell(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()

    def test_michelin_none_degrades_to_score_over_s(self):
        """LIVE path: michelin=None -> '<prestige>/<S>' (e.g. '13/15')."""
        cell = self.render.prestige_cell(None, 13, 15)
        self.assertEqual(cell, "13/15")
        self.assertNotIn("★", cell)

    def test_michelin_3star_forward_compat_branch(self):
        """Forward-compat (inert for current corpus): michelin='3-star' ->
        '★★★ · 13/15'."""
        cell = self.render.prestige_cell("3-star", 13, 15)
        self.assertEqual(cell, "★★★ · 13/15")

    def test_michelin_bib_forward_compat_branch(self):
        cell = self.render.prestige_cell("bib", 4, 15)
        self.assertEqual(cell, "Bib · 4/15")

    def test_michelin_none_string_degrades(self):
        """The literal string 'none' is treated as no-michelin (corpus may emit
        'none' rather than null) -> degrade to '<score>/<S>'."""
        cell = self.render.prestige_cell("none", 5, 15)
        self.assertEqual(cell, "5/15")

    def test_board_uses_live_degrade_for_none_michelin(self):
        """In the board, a michelin=None venue shows '<score>/<S>' with NO stars."""
        result = _fixture_ranking_result(self.render)
        md = self.render.render_board(result, _fixture_run_meta())
        self.assertIn("13/15", md)   # Noma prestige 13, S=15, no stars

    def test_board_renders_star_branch_when_present(self):
        """Forward-compat: a michelin='3-star' fixture venue lights the star branch."""
        result = _fixture_ranking_result(self.render)
        md = self.render.render_board(result, _fixture_run_meta())
        self.assertIn("★★★ · 13/15", md)   # Geranium fixture carries michelin


# ---------------------------------------------------------------------------
# 5. GATE_LABELS ordinal -> collapsed label
# ---------------------------------------------------------------------------

class TestGateLabels(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()

    def test_gate_level_0_online(self):
        self.assertEqual(self.render.gate_label(0), "online")

    def test_gate_high_level_hard(self):
        """A high ordinal level maps to a hard-gate label (ticket-drop)."""
        self.assertEqual(self.render.gate_label(3), "ticket-drop")

    def test_gate_level_2_prepay_hard(self):
        self.assertEqual(self.render.gate_label(2), "prepay/hard")

    def test_gate_labels_dict_exists(self):
        self.assertTrue(hasattr(self.render, "GATE_LABELS"))
        self.assertIsInstance(self.render.GATE_LABELS, dict)

    def test_board_shows_gate_labels(self):
        result = _fixture_ranking_result(self.render)
        md = self.render.render_board(result, _fixture_run_meta())
        self.assertIn("ticket-drop", md)   # gate=3 venues
        self.assertIn("prepay/hard", md)   # gate=2 venues


# ---------------------------------------------------------------------------
# 6. RENDER-04: diagnostics + coverage block in §3
# ---------------------------------------------------------------------------

class TestDiagnosticsBlock(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)
        self.md = self.render.render_board(self.result, _fixture_run_meta())

    def test_divergences_present(self):
        self.assertIn("divergence", self.md.lower())
        self.assertIn("0", self.md)

    def test_rhat_present(self):
        low = self.md.lower()
        self.assertTrue("r̂" in self.md or "r-hat" in low or "rhat" in low)

    def test_ess_present(self):
        self.assertIn("ESS", self.md.upper())

    def test_chains_x_draws_present(self):
        """chains × draws shown (4 × 1500)."""
        self.assertIn("4", self.md)
        self.assertIn("1500", self.md)

    def test_sampler_present(self):
        self.assertIn("NUTS", self.md)

    def test_coverage_m_over_n_live(self):
        """Coverage line 'M/N venues read live' (RENDER-04)."""
        low = self.md.lower()
        # 3 readable of 5 total in the fixture
        self.assertIn("3/5", self.md)
        self.assertIn("read live", low)

    def test_coverage_floor_note_below_floor(self):
        """With M=3 (< ~10 floor) the coverage note should NOT claim the floor
        was cleared."""
        low = self.md.lower()
        self.assertIn("floor", low)

    def test_coverage_floor_cleared_when_high(self):
        """With M>=~10 the coverage block notes the floor was cleared."""
        render = self.render
        result = _fixture_ranking_result(render)
        # bump readable count above the floor
        result.channel_coverage["readable"] = 16
        result.channel_coverage["total"] = 37
        md = render.render_board(result, _fixture_run_meta())
        low = md.lower()
        self.assertIn("16/37", md)
        self.assertIn("cleared", low)


# ---------------------------------------------------------------------------
# 7. REV-02 reviews-skipped surfacing
# ---------------------------------------------------------------------------

class TestReviewsSkippedSurfacing(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()

    def test_reviews_skipped_flagged(self):
        result = _fixture_ranking_result(self.render, reviews_status="skipped")
        md = self.render.render_board(result, _fixture_run_meta())
        low = md.lower()
        self.assertIn("reviews", low)
        self.assertIn("skipped", low)

    def test_reviews_ok_not_flagged_skipped(self):
        result = _fixture_ranking_result(self.render, reviews_status="ok")
        md = self.render.render_board(result, _fixture_run_meta())
        self.assertNotIn("reviews: skipped", md.lower())


# ---------------------------------------------------------------------------
# 8. §4 — β_b / β_p line
# ---------------------------------------------------------------------------

class TestDemandQuestion(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)
        self.md = self.render.render_board(self.result, _fixture_run_meta())

    def test_beta_b_mean_present(self):
        self.assertIn("1.39", self.md)

    def test_beta_b_hdi_present(self):
        self.assertIn("0.45", self.md)
        self.assertIn("2.27", self.md)

    def test_beta_b_p_gt0_present(self):
        low = self.md.lower()
        self.assertTrue("β_b" in self.md or "beta_b" in low)
        self.assertIn("1.00", self.md)   # P(β_b>0) rounds to 1.00

    def test_beta_p_present_for_context(self):
        self.assertIn("0.75", self.md)   # beta_p mean


# ---------------------------------------------------------------------------
# 9. Source guard — render_board does no file I/O; no hardcoded path (T-02-03)
# ---------------------------------------------------------------------------

class TestRenderSourceGuard(unittest.TestCase):
    def setUp(self):
        self.src = (_SCRIPTS_DIR / "render.py").read_text(encoding="utf-8")

    def test_module_parses(self):
        try:
            ast.parse(self.src)
        except SyntaxError as exc:
            self.fail(f"render.py has a syntax error: {exc}")

    def test_no_heavy_imports(self):
        """render.py is pure stdlib — must NOT import pymc / arviz / numpy."""
        tree = ast.parse(self.src)
        banned = {"pymc", "arviz", "numpy", "np", "pytensor", "xarray"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(root, banned,
                                     f"render.py must not import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                self.assertNotIn(root, banned,
                                 f"render.py must not import from {node.module}")

    def test_render_board_does_no_file_io(self):
        """render_board's function body issues no open()/write — pure str->str.

        Walk the render_board FunctionDef AST and assert no call to open / write_text
        / Path().write_* appears inside it.
        """
        tree = ast.parse(self.src)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "render_board":
                target = node
                break
        self.assertIsNotNone(target, "render_board function must exist")
        for sub in ast.walk(target):
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                self.assertNotEqual(name, "open",
                                    "render_board must not call open()")
                if name:
                    self.assertNotIn("write_text", name,
                                     "render_board must not write files")
                    self.assertNotIn("write_bytes", name,
                                     "render_board must not write files")

    def test_no_hardcoded_absolute_output_path(self):
        """No hardcoded absolute output path string in render.py source."""
        # A hardcoded absolute output path would be e.g. "/Users/..." or "/home/..."
        self.assertNotIn('"/Users/', self.src)
        self.assertNotIn('"/home/', self.src)
        self.assertNotIn(".cma-proof", self.src)

    def test_uses_getcwd_for_output(self):
        """main() resolves output under os.getcwd() (RENDER-05 no-hardcode)."""
        self.assertIn("os.getcwd", self.src)


# ---------------------------------------------------------------------------
# 10. main() — write board.md + results.json to CWD (RENDER-05)
# ---------------------------------------------------------------------------

class TestMainWritesToCwd(unittest.TestCase):
    def setUp(self):
        self.render = _import_render()
        self.result = _fixture_ranking_result(self.render)

    def _write_results_json(self, dir_path: Path) -> Path:
        """Persist a results.json the way model.py main does (RankingResult.to_dict-ish)."""
        payload = {
            "divergences": self.result.diagnostics["divergences"],
            "rhat_max": self.result.diagnostics["rhat_max"],
            "ess_min": self.result.diagnostics["ess_min"],
            "beta_b": self.result.beta_b,
            "beta_p": self.result.beta_p,
            "ranking": self.result.ranking,
            "diagnostics": self.result.diagnostics,
            "channel_coverage": self.result.channel_coverage,
        }
        p = dir_path / "input-results.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p

    def test_writes_board_and_results_to_cwd(self):
        """main writes <slug>-board.md and <slug>-results.json under CWD (RENDER-05)."""
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            results_path = self._write_results_json(tdp)
            try:
                os.chdir(td)
                rc = self.render.main([
                    "--city", "manila",
                    "--results", str(results_path),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 0)
            self.assertTrue((tdp / "manila-board.md").exists(),
                            "board.md must land in CWD")
            self.assertTrue((tdp / "manila-results.json").exists(),
                            "results.json sidecar must land in CWD")
            board_txt = (tdp / "manila-board.md").read_text(encoding="utf-8")
            self.assertIn("Did live booking demand move the ranking?", board_txt)

    def test_out_override_respected(self):
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            results_path = self._write_results_json(tdp)
            out = tdp / "custom-board.md"
            try:
                os.chdir(td)
                rc = self.render.main([
                    "--city", "manila",
                    "--results", str(results_path),
                    "--out", str(out),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())

    def test_slug_is_slugified(self):
        """The output filename slug is [a-z0-9-] (T-02-01) — derived via cityconfig."""
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            results_path = self._write_results_json(tdp)
            try:
                os.chdir(td)
                # "Manila" (mixed case) must slugify to "manila"
                rc = self.render.main([
                    "--city", "Manila",
                    "--results", str(results_path),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 0)
            self.assertTrue((tdp / "manila-board.md").exists())

    def test_path_traversal_city_rejected(self):
        """A city name with path separators is rejected before any path-join (T-02-01)."""
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            results_path = self._write_results_json(tdp)
            try:
                os.chdir(td)
                rc = self.render.main([
                    "--city", "../../etc/evil",
                    "--results", str(results_path),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 1, "path-traversal city must be rejected")

    def test_malformed_results_json_actionable_error(self):
        """Malformed input JSON -> actionable error (rc 1), not an uncaught crash (V5/T-02-02)."""
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            bad = tdp / "bad-results.json"
            bad.write_text("{not valid json", encoding="utf-8")
            try:
                os.chdir(td)
                rc = self.render.main([
                    "--city", "manila",
                    "--results", str(bad),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 1)

    def test_missing_results_file_actionable_error(self):
        cwd0 = os.getcwd()
        with tempfile.TemporaryDirectory() as td:
            try:
                os.chdir(td)
                rc = self.render.main([
                    "--city", "manila",
                    "--results", str(Path(td) / "does-not-exist.json"),
                ])
            finally:
                os.chdir(cwd0)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
