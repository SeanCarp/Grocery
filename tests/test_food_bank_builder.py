import unittest

from food_bank_builder import AccessBlocked, wait_for_access


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


if __name__ == "__main__":
    unittest.main()
