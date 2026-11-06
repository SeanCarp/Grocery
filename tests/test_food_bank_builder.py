import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import food_bank_builder
from food_bank_builder import (
    TILE_COUNT,
    AccessBlocked,
    StoreDefinition,
    run_search,
    store_choice,
    wait_for_access,
    wait_for_results,
)


class FakePage:
    """Returns one DataDome challenge type ('bv', 'fe' or None) per evaluate()."""

    def __init__(self, challenges):
        self.challenges = iter(challenges)
        self.sleeps = 0

    def evaluate(self, expression):
        return next(self.challenges)

    def sleep(self, seconds):
        self.sleeps += 1


class WaitForAccessTests(unittest.TestCase):
    def test_hard_block_fails_without_waiting(self):
        page = FakePage(["bv"])
        with self.assertRaises(AccessBlocked):
            wait_for_access(page, headless=False)
        self.assertEqual(page.sleeps, 0)

    def test_captcha_fails_immediately_when_headless(self):
        with self.assertRaises(AccessBlocked):
            wait_for_access(FakePage(["fe"]), headless=True)

    def test_headed_captcha_waits_until_solved(self):
        page = FakePage(["fe", "fe", None])
        wait_for_access(page, headless=False)
        self.assertEqual(page.sleeps, 2)


class ResultsPage:
    """No DataDome challenge; answers the tile count and the 'no results' check."""

    def __init__(self, tiles, no_results):
        self.tiles = tiles
        self.no_results = no_results

    def evaluate(self, expression):
        if expression == food_bank_builder.DATADOME_CHALLENGE:
            return None
        return self.tiles if expression == TILE_COUNT else self.no_results

    def sleep(self, seconds):
        pass


class WaitForResultsTests(unittest.TestCase):
    def test_tiles_on_page(self):
        self.assertTrue(wait_for_results(ResultsPage(tiles=15, no_results=False), headless=False))

    def test_store_reports_no_results(self):
        self.assertFalse(wait_for_results(ResultsPage(tiles=0, no_results=True), headless=False))


class StoreChoiceTests(unittest.TestCase):
    def test_any_letter_case(self):
        self.assertIs(store_choice("food lion"), StoreDefinition.FOODLION)
        self.assertIs(store_choice("GIANT FOODS"), StoreDefinition.GIANT)

    def test_unbuilt_store_is_rejected(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            store_choice("Kroger")


class HardBlockTests(unittest.TestCase):
    def test_hard_block_resets_the_browser_profile(self):
        blocked_browser = mock.Mock()
        blocked_browser.evaluate.return_value = "bv"
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / ".chrome-profile"
            profile.mkdir()
            with mock.patch.object(food_bank_builder, "PROJECT_DIR", Path(directory)), mock.patch.object(
                food_bank_builder, "browser_binary", return_value="/usr/bin/google-chrome"
            ), mock.patch.object(food_bank_builder.sb_cdp, "Chrome", return_value=blocked_browser):
                with self.assertRaises(food_bank_builder.HardBlock):
                    food_bank_builder.search_with_browser(
                        food_bank_builder.GroceryStores[StoreDefinition.FOODLION], "bread", headless=False
                    )
            self.assertFalse(profile.exists())
        blocked_browser.quit.assert_called_once()


class PersonalProfileTests(unittest.TestCase):
    """--use-my-profile: the browser only ever sees a throwaway copy of the real profile."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.real = Path(directory.name) / "Brave-Browser"
        (self.real / "Default" / "Cache").mkdir(parents=True)
        (self.real / "Default" / "Cookies").write_text("cookies")
        (self.real / "Default" / "Cache" / "data_0").write_text("cache")
        (self.real / "SingletonLock").write_text("lock")
        (self.real / "Local State").write_text(json.dumps({"profile": {"last_used": "Default"}}))
        self.copies = Path(directory.name) / "copies"
        for name, value in [
            ("personal_profile", mock.Mock(return_value=self.real)),
            ("browser_binary", mock.Mock(return_value="/usr/bin/brave")),
            ("PROFILE_COPY_DIR", self.copies),
        ]:
            patcher = mock.patch.object(food_bank_builder, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_copy_skips_caches_and_locks(self):
        profile_dir, options = food_bank_builder.browser_launch("brave", use_my_profile=True)
        self.assertEqual(profile_dir, self.copies / "brave-profile")
        self.assertEqual((profile_dir / "Default" / "Cookies").read_text(), "cookies")
        self.assertTrue((profile_dir / "Local State").is_file())
        self.assertFalse((profile_dir / "Default" / "Cache").exists())
        self.assertFalse((profile_dir / "SingletonLock").exists())
        self.assertIn("--profile-directory=Default", options["browser_args"])
        self.assertEqual(options["browser_executable_path"], "/usr/bin/brave")

    def test_kde_uses_kwallet(self):
        with mock.patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "6"}):
            self.assertEqual(food_bank_builder.linux_password_store(), "kwallet6")
        with mock.patch.dict("os.environ", {"XDG_CURRENT_DESKTOP": "GNOME"}):
            self.assertEqual(food_bank_builder.linux_password_store(), "gnome-libsecret")

    def test_copy_is_deleted_and_real_profile_untouched(self):
        browser = mock.Mock()
        browser.evaluate.return_value = "bv"
        with mock.patch.object(food_bank_builder.sb_cdp, "Chrome", return_value=browser) as chrome:
            with self.assertRaises(food_bank_builder.HardBlock):
                food_bank_builder.search_with_browser(
                    food_bank_builder.GroceryStores[StoreDefinition.GIANT], "milk", headless=False,
                    browser="brave", use_my_profile=True,
                )
        self.assertEqual(chrome.call_args.kwargs["user_data_dir"], str(self.copies / "brave-profile"))
        self.assertFalse((self.copies / "brave-profile").exists())
        self.assertEqual((self.real / "Default" / "Cookies").read_text(), "cookies")
        self.assertTrue((self.real / "SingletonLock").exists())


class RunSearchTests(unittest.TestCase):
    PRODUCT = {"id": "154242", "name": "Butter Bread", "price": "$3.99", "raw_text": "Butter Bread"}

    def test_browser_results_are_saved(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            food_bank_builder, "search_with_browser", return_value=([self.PRODUCT], "<html></html>")
        ):
            run_directory = run_search(StoreDefinition.FOODLION, "bread", directory)
            saved = json.loads((run_directory / "results.json").read_text())
            csv_text = (run_directory / "results.csv").read_text()
            raw_html = (run_directory / "raw" / "page-001.html").read_text()

        self.assertEqual(run_directory.name.split("_")[:3], ["bread", "Food", "Lion"])
        self.assertEqual(saved["product_count"], 1)
        self.assertEqual(saved["store"], "Food Lion")
        self.assertIn("Butter Bread,,$3.99", csv_text)
        self.assertEqual(raw_html, "<html></html>")

    def test_failed_search_leaves_no_folder(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            food_bank_builder, "search_with_browser", side_effect=AccessBlocked("blocked")
        ):
            with self.assertRaises(AccessBlocked):
                run_search(StoreDefinition.GIANT, "bread", directory)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
