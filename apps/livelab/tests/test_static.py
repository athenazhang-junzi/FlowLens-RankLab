from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LiveLabStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "styles.css").read_text(encoding="utf-8")
        cls.js = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.offline_run = (ROOT / "data" / "ranklab_offline_run.js").read_text(encoding="utf-8")

    def test_required_files_exist(self):
        for name in [
            "README.md",
            "index.html",
            "styles.css",
            "app.js",
            "data/ranklab_offline_run.js",
        ]:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_evidence_boundary_is_visible_and_documented(self):
        for content in [self.html, self.readme]:
            self.assertIn("模拟", content)
            self.assertRegex(content, r"不代表|不能表述|不把")

    def test_five_workspace_views_are_present(self):
        for view in ["overview", "strategy", "health", "metrics", "decision"]:
            self.assertIn(f'data-view="{view}"', self.html)
            self.assertRegex(self.js, rf"\b{view}: render")

    def test_health_checks_cover_required_risks(self):
        for marker in ["srm", "trigger", "contamination", "completeness", "version"]:
            self.assertIn(f'id: "{marker}"', self.js)

    def test_event_contract_is_complete(self):
        event_chain = "eligible → assigned → exposed → clicked → content_start → long_view / negative_feedback"
        self.assertIn(event_chain, self.js)

    def test_accessibility_basics(self):
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('aria-current="page"', self.html)
        self.assertIn("focus-visible", self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertNotIn('tabindex="1"', self.html)

    def test_responsive_breakpoints_exist(self):
        for breakpoint in ["1180px", "960px", "720px", "520px"]:
            self.assertIn(breakpoint, self.css)

    def test_no_known_placeholder_or_ai_slop_copy(self):
        combined = "\n".join([self.html, self.css, self.js])
        banned = [
            "Lorem ipsum",
            "John Doe",
            "Jane Doe",
            "example@example.com",
            "#0D0B1A",
            "#1A1625",
            "pink-cyan",
            "purple-blue",
        ]
        for token in banned:
            self.assertNotIn(token, combined)

    def test_buttons_declare_button_type(self):
        button_tags = re.findall(r"<button\b[^>]*>", self.html)
        self.assertGreaterEqual(len(button_tags), 8)
        for tag in button_tags:
            self.assertIn('type="button"', tag)

    def test_no_external_business_api(self):
        self.assertNotIn("fetch(", self.js)
        self.assertNotIn("XMLHttpRequest", self.js)
        self.assertNotIn("axios", self.js)

    def test_gatec_offline_artifact_is_visible_and_bounded(self):
        self.assertIn("ranklab_offline_run.js", self.html)
        self.assertIn("renderOfflineRun", self.js)
        self.assertIn("gatec-eval-", self.offline_run)
        self.assertIn("ITERATE_AND_RETEST", self.offline_run)
        self.assertIn("offline replay", self.offline_run)
        self.assertIn("E3", self.offline_run)

    def test_interaction_feedback_and_drilldowns_exist(self):
        for marker in [
            "lastBatchReceipt",
            "simulationPhase",
            'data-check-id=',
            'data-check-detail=',
            'data-metric-index=',
            'class="metric-inspector"',
            "有未保存修改",
        ]:
            self.assertIn(marker, self.js)

    def test_new_interactions_keep_accessible_state(self):
        for marker in [
            'role="status"',
            'aria-live="polite"',
            'aria-pressed=',
            'aria-busy',
            'aria-label="关闭本次批次回执"',
        ]:
            self.assertIn(marker, self.js)


if __name__ == "__main__":
    unittest.main()
