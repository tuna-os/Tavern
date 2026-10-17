# test_brew_missing.py - Tests for missing Homebrew detection and install offer
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
import tavern.brew_env as be


class TestIsBrewAvailable:
    def test_available_with_valid_path(self):
        assert be.is_brew_available('/home/linuxbrew/.linuxbrew/bin/brew') is True
        assert be.is_brew_available('/usr/local/bin/brew') is True
        assert be.is_brew_available('/opt/homebrew/bin/brew') is True

    def test_unavailable_with_bare_brew_fallback(self):
        # The fallback sentinel 'brew' means brew executable was not found
        assert be.is_brew_available('brew') is False

    def test_unavailable_with_empty_or_none(self):
        assert be.is_brew_available('') is False
        assert be.is_brew_available(None) is False or be.is_brew_available(be.BREW_BIN)


class TestShouldOfferHomebrewInstall:
    def test_offers_when_brew_missing(self):
        assert be.should_offer_homebrew_install(brew_bin='brew') is True
        assert be.should_offer_homebrew_install(brew_bin='') is True

    def test_does_not_offer_when_brew_present(self):
        assert be.should_offer_homebrew_install(brew_bin='/home/linuxbrew/.linuxbrew/bin/brew') is False

    def test_installed_count_zero_alone_does_not_trigger_if_brew_present(self):
        # Healthy host with zero packages installed should NOT be offered Homebrew install
        assert be.should_offer_homebrew_install(
            brew_bin='/home/linuxbrew/.linuxbrew/bin/brew', installed_count=0) is False


class TestRefreshBrewBin:
    def test_refresh_brew_bin_updates_global(self, monkeypatch):
        orig_bin = be.BREW_BIN
        monkeypatch.setattr(be, '_find_brew', lambda: '/custom/path/bin/brew')
        try:
            new_bin = be.refresh_brew_bin()
            assert new_bin == '/custom/path/bin/brew'
            assert be.BREW_BIN == '/custom/path/bin/brew'
        finally:
            be.BREW_BIN = orig_bin

class TestHomebrewInstallerCommands:
    def test_build_homebrew_install_command_native(self):
        cmd = be.build_homebrew_install_command(in_flatpak=False)
        assert cmd[0] == '/bin/bash'
        assert cmd[1] == '-c'
        assert be.HOMEBREW_INSTALL_URL in cmd[2]
        assert 'curl' in cmd[2]

    def test_build_homebrew_install_command_flatpak(self):
        cmd = be.build_homebrew_install_command(in_flatpak=True)
        assert cmd[0] == 'flatpak-spawn'
        assert '--host' in cmd
        joined = ' '.join(cmd)
        assert be.HOMEBREW_INSTALL_URL in joined

    def test_find_terminal_emulator(self):
        def fake_which(cmd):
            return '/usr/bin/' + cmd if cmd == 'ptyxis' else None

        chosen = be.find_terminal_emulator(
            candidates=('xdg-terminal-exec', 'ptyxis', 'gnome-terminal'),
            which=fake_which,
        )
        assert chosen == 'ptyxis'

    def test_find_terminal_emulator_none_available(self):
        assert be.find_terminal_emulator(which=lambda _cmd: None) is None

    def test_build_terminal_install_argv_native(self):
        argv = be.build_terminal_install_argv(
            terminal_bin='ptyxis',
            install_cmd=['/bin/bash', '-c', 'echo install'],
            in_flatpak=False,
        )
        assert argv[0] == 'ptyxis'
        assert '--' in argv
        assert '/bin/bash' in argv
        assert 'echo install' in ' '.join(argv)

    def test_build_terminal_install_argv_flatpak(self):
        argv = be.build_terminal_install_argv(
            terminal_bin='ptyxis',
            install_cmd=['/bin/bash', '-c', 'echo install'],
            in_flatpak=True,
        )
        assert argv[0] == 'flatpak-spawn'
        assert '--host' in argv
        assert 'ptyxis' in argv
        assert 'echo install' in ' '.join(argv)

    def test_build_terminal_install_argv_none_terminal(self):
        assert be.build_terminal_install_argv(None) is None


class TestWindowBannerState:
    def test_banner_revealed_when_brew_missing(self, monkeypatch):
        from tavern.window import TavernWindow

        class MockBanner:
            def __init__(self):
                self.revealed = None
            def set_revealed(self, val):
                self.revealed = val

        class MockWindow:
            def __init__(self):
                self.brew_missing_banner = MockBanner()

        mock_win = MockWindow()
        monkeypatch.setattr(be, 'is_brew_available', lambda *a: False)
        assert TavernWindow._update_brew_missing_banner(mock_win) is True
        assert mock_win.brew_missing_banner.revealed is True

    def test_banner_hidden_when_brew_available(self, monkeypatch):
        from tavern.window import TavernWindow

        class MockBanner:
            def __init__(self):
                self.revealed = None
            def set_revealed(self, val):
                self.revealed = val

        class MockWindow:
            def __init__(self):
                self.brew_missing_banner = MockBanner()

        mock_win = MockWindow()
        monkeypatch.setattr(be, 'is_brew_available', lambda *a: True)
        assert TavernWindow._update_brew_missing_banner(mock_win) is False
        assert mock_win.brew_missing_banner.revealed is False
