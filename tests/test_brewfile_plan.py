from tavern.brewfile_plan import BrewfilePlan, build_plan


def test_build_plan_filters_failed_entries_but_keeps_formulae():
    parsed = {
        'taps': ['good/tap', {'name': 'bad/tap', 'trusted': True}],
        'formulae': ['wget'],
        'casks': ['good-cask', 'bad-cask'],
        'flatpaks': ['org.example.Good', 'org.example.Bad'],
    }

    plan = build_plan(
        parsed,
        tap_errors={'bad/tap'},
        cask_errors={'bad-cask'},
        flatpak_errors={'org.example.Bad'},
    )

    assert plan == BrewfilePlan(
        taps=('good/tap',),
        formulae=('wget',),
        casks=('good-cask',),
        flatpaks=('org.example.Good',),
    )


def test_render_preserves_trusted_taps_and_order():
    plan = BrewfilePlan(
        taps=({'name': 'homebrew/core', 'trusted': True}, 'other/tap'),
        formulae=('git',),
        casks=('firefox',),
        flatpaks=('org.example.App',),
    )

    assert plan.render() == (
        'tap "homebrew/core", trusted: true\n'
        'tap "other/tap"\n'
        'brew "git"\n'
        'cask "firefox"\n'
        'flatpak "org.example.App"\n'
    )


def test_empty_plan_renders_empty_string():
    assert build_plan({}).render() == ''
