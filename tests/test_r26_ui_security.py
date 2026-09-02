from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
APP_SOURCE = (APP_DIR / "app.py").read_text(encoding="utf-8")

from config import GOOGLE_SHEETS
from db import _csv_safe_cell
from google_sheets_sync import _verify_expected_role


def load_pure_helpers(*names: str) -> dict[str, object]:
    tree = ast.parse(APP_SOURCE)
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace: dict[str, object] = {"urlsplit": urlsplit}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_DIR / "app.py"), "exec"), namespace)
    return namespace


class UniqueOptionContractTest(unittest.TestCase):
    def test_duplicate_labels_preserve_every_target(self) -> None:
        helper = load_pure_helpers("_unique_option_map")["_unique_option_map"]

        options = helper([
            ("같은 제목", 11),
            ("같은 제목", 22),
            ("같은 제목 · 1/2", 33),
            ("다른 제목", 44),
        ])

        self.assertEqual(list(options.values()), [11, 22, 33, 44])
        self.assertEqual(len(options), 4)
        self.assertEqual(len(set(options)), 4)
        self.assertTrue(any("1/2" in label for label in options))
        self.assertTrue(any("2/2" in label for label in options))


class ExternalUrlSafetyContractTest(unittest.TestCase):
    def test_only_plain_http_links_are_rendered(self) -> None:
        helper = load_pure_helpers("_safe_http_url")["_safe_http_url"]

        self.assertEqual(helper("example.com/path"), "https://example.com/path")
        self.assertEqual(helper("https://example.com/path"), "https://example.com/path")
        self.assertEqual(helper("javascript:alert(1)"), "")
        self.assertEqual(helper("data:text/html,test"), "")
        self.assertEqual(helper("https://user:pass@example.com"), "")
        self.assertEqual(helper("https://example.com/a b"), "")


class PublicBoardContractTest(unittest.TestCase):
    def test_public_comments_cannot_spoof_reserved_log_markers(self) -> None:
        helper = load_pure_helpers("_has_reserved_review_prefix")["_has_reserved_review_prefix"]

        self.assertTrue(helper("[기준 확정] 임의 문구"))
        self.assertTrue(helper("  [또 발생] 임의 문구"))
        self.assertFalse(helper("일반 확인 댓글"))

    def test_public_add_and_reply_flow_remains_available(self) -> None:
        self.assertIn("누구나 새 확인사항과 댓글을 남길 수 있어요", APP_SOURCE)
        self.assertIn('key="open_review_item_form"', APP_SOURCE)
        self.assertIn('key=f"open_review_reply_{item[\'id\']}"', APP_SOURCE)


class SearchAccessContractTest(unittest.TestCase):
    def test_viewer_search_hides_team_only_operating_records(self) -> None:
        helper = load_pure_helpers("_visible_search_results")["_visible_search_results"]
        results = [
            {"id": 1, "target_page": "매뉴얼"},
            {"id": 2, "target_page": "결정·운영로그"},
            {"id": 3, "target_page": "행사"},
        ]

        viewer_results = helper(results, allow_team_content=False)
        team_results = helper(results, allow_team_content=True)

        self.assertEqual([item["id"] for item in viewer_results], [1, 3])
        self.assertEqual([item["id"] for item in team_results], [1, 2, 3])

    def test_attendance_raw_source_details_are_admin_only(self) -> None:
        tree = ast.parse(APP_SOURCE)
        attendance = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "attendance_page"
        )
        guarded_admin_call = False
        for node in ast.walk(attendance):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
                continue
            if not isinstance(node.test.func, ast.Name) or node.test.func.id != "has_access":
                continue
            if not node.test.args or not isinstance(node.test.args[0], ast.Constant):
                continue
            if node.test.args[0].value != "ADMIN":
                continue
            guarded_admin_call = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "_attendance_admin_quality"
                for statement in node.body for child in ast.walk(statement)
            )
        self.assertTrue(guarded_admin_call)

    def test_pending_only_attendance_still_shows_admin_quality(self) -> None:
        tree = ast.parse(APP_SOURCE)
        attendance = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "attendance_page"
        )
        pending_only_branch = next(
            node for node in ast.walk(attendance)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Attribute)
            and isinstance(node.test.value, ast.Name)
            and node.test.value.id == "sunday_data"
            and node.test.attr == "empty"
            and any(isinstance(statement, ast.Return) for statement in node.body)
        )
        calls_quality = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_attendance_admin_quality"
            for statement in pending_only_branch.body for child in ast.walk(statement)
        )
        self.assertTrue(calls_quality)

    def test_dashboard_keeps_pending_only_sunday_count_visible(self) -> None:
        self.assertIn(
            "elif missing_attendance_dates:\n        attendance_label = (",
            APP_SOURCE,
        )


class ExternalReadOnlyContractTest(unittest.TestCase):
    def test_source_google_sheets_and_calendar_use_readonly_scopes(self) -> None:
        sheets_source = (APP_DIR / "google_sheets_sync.py").read_text(encoding="utf-8")
        calendar_source = (APP_DIR / "calendar_sync.py").read_text(encoding="utf-8")

        self.assertIn("https://www.googleapis.com/auth/drive.readonly", sheets_source)
        self.assertIn("https://www.googleapis.com/auth/calendar.readonly", calendar_source)

    def test_each_google_sheet_requires_its_expected_workbook_role(self) -> None:
        roles = {str(sheet["expected_role"]) for sheet in GOOGLE_SHEETS}
        self.assertEqual(roles, {"MANUALS", "LINEUP_ATTENDANCE"})
        for sheet in GOOGLE_SHEETS:
            _verify_expected_role(sheet, {"role": sheet["expected_role"]})
            wrong_role = "LINEUP_ATTENDANCE" if sheet["expected_role"] == "MANUALS" else "MANUALS"
            with self.assertRaises(RuntimeError):
                _verify_expected_role(sheet, {"role": wrong_role})


class DeploymentPrivacyContractTest(unittest.TestCase):
    def test_operational_data_and_secrets_are_git_ignored(self) -> None:
        ignore_source = (APP_DIR / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("data/*.db", ignore_source)
        self.assertIn("data/import_report*.json", ignore_source)
        self.assertIn(".streamlit/secrets.toml", ignore_source)
        self.assertIn("*service_account*.json", ignore_source)

    def test_empty_deploy_rebuilds_from_readonly_google_sheets(self) -> None:
        tree = ast.parse(APP_SOURCE)
        bootstrap = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "bootstrap"
        )
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sync_google_sheets"
            for node in ast.walk(bootstrap)
        ))

    def test_csv_backup_neutralizes_spreadsheet_formulas(self) -> None:
        for value in ("=HYPERLINK('x')", "+SUM(1,2)", "-2+3", "@cmd", "  =1+1"):
            self.assertTrue(str(_csv_safe_cell(value)).startswith("'"))
        self.assertEqual(_csv_safe_cell("ordinary text"), "ordinary text")
        self.assertEqual(_csv_safe_cell(-3), -3)


class AccessSecurityContractTest(unittest.TestCase):
    def test_access_numbers_have_lockout_and_session_expiry(self) -> None:
        self.assertIn("ACCESS_SESSION_SECONDS = 60 * 60", APP_SOURCE)
        self.assertIn("ACCESS_MAX_FAILURES = 5", APP_SOURCE)
        self.assertIn("ACCESS_LOCK_SECONDS = 10 * 60", APP_SOURCE)
        self.assertIn('st.session_state["_access_expires_at"]', APP_SOURCE)
        self.assertIn(
            'role != "VIEWER" and (expires_at <= 0 or time.time() >= expires_at)',
            APP_SOURCE,
        )

    def test_legacy_delete_pin_is_not_an_admin_fallback(self) -> None:
        self.assertNotIn(
            'get_secret("ADMIN_ACCESS_PIN") or get_secret("REVIEW_BOARD_DELETE_PIN")',
            APP_SOURCE,
        )


class BibleInputSafetyContractTest(unittest.TestCase):
    def test_corpus_upload_is_admin_only_and_size_bounded(self) -> None:
        tree = ast.parse(APP_SOURCE)
        bible_page = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "bible_page"
        )
        admin_upload = False
        for node in ast.walk(bible_page):
            if not isinstance(node, ast.If) or not isinstance(node.test, ast.Call):
                continue
            if not isinstance(node.test.func, ast.Name) or node.test.func.id != "has_access":
                continue
            if not node.test.args or not isinstance(node.test.args[0], ast.Constant):
                continue
            if node.test.args[0].value != "ADMIN":
                continue
            admin_upload = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "file_uploader"
                and any(
                    keyword.arg == "max_upload_size"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value == 10
                    for keyword in child.keywords
                )
                for statement in node.body for child in ast.walk(statement)
            )
        self.assertTrue(admin_upload)

    def test_bible_cache_and_pasted_text_are_bounded(self) -> None:
        self.assertIn("@st.cache_data(show_spinner=False, max_entries=4)", APP_SOURCE)
        self.assertIn("max_chars=20_000", APP_SOURCE)


class VisualAccessibilityContractTest(unittest.TestCase):
    def test_caption_color_and_touch_targets_keep_mobile_contrast(self) -> None:
        self.assertIn("--text-3:#667180", APP_SOURCE)
        self.assertIn("min-height:2.75rem", APP_SOURCE)
        self.assertNotIn("label > div:first-child { display:none", APP_SOURCE)

    def test_streamlit_chrome_is_quiet_but_sidebar_control_remains_visible(self) -> None:
        self.assertIn('[data-testid="stToolbar"] { display:flex', APP_SOURCE)
        self.assertIn('[data-testid="stMainMenu"]', APP_SOURCE)
        self.assertIn('[data-testid="stAppDeployButton"]', APP_SOURCE)
        self.assertIn('button[data-testid="stExpandSidebarButton"]', APP_SOURCE)

    def test_current_tab_and_mobile_controls_use_current_streamlit_selectors(self) -> None:
        self.assertIn('[data-testid="stTab"][aria-selected="true"]', APP_SOURCE)
        self.assertIn('[data-testid="stCheckbox"] label', APP_SOURCE)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr)) !important', APP_SOURCE)
        self.assertIn('text-align:center;color:#667180;font-size:.78rem', APP_SOURCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
