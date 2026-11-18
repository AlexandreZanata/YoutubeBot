"""The desktop launcher must keep the window identity and initial size the owner needs."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "desktop/scripts/install.sh"
MAIN = ROOT / "desktop/apps/manager/src/main.rs"


class DesktopLauncherContractTests(unittest.TestCase):
    def test_desktop_entry_keeps_the_taskbar_identity(self):
        script = INSTALL.read_text(encoding="utf-8")
        self.assertIn('BINARY="${BIN_DIR}/ytbot-manager"', script)
        self.assertIn("Icon=ytbot-manager", script)
        self.assertIn("StartupWMClass=ytbot-manager", script)

    def test_app_sets_the_xdg_id_and_sizes_before_showing(self):
        source = MAIN.read_text(encoding="utf-8")
        self.assertIn('slint::set_xdg_app_id("ytbot-manager")', source)
        self.assertIn("BackendSelector::new()", source)
        size = source.index("set_size(slint::LogicalSize::new(1280.0, 800.0))")
        show = source.index("ui.show()?")
        self.assertLess(size, show)
        self.assertNotIn("Timer::single_shot(Duration::from_millis(0)", source)


if __name__ == "__main__":
    unittest.main()
