pkgdatadir = PKGDATADIR

blueprints = custom_target('blueprints',
  input: files(
    'window.blp',
    'package-tile.blp',
    'package-details.blp',
    'search-page.blp',
    'browse-page.blp',
    'installed-page.blp',
    'tap-page.blp',
    'task-panel.blp',
    'brewfile-dialog.blp',
    'brewfile-page.blp',
    'stats-dialog.blp',
  ),
  output: '.',
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

gnome.compile_resources('tavern',
  'tavern.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

configure_file(
  input: 'tavern.in',
  output: 'tavern',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

# Install Python sources
tavern_sources = [
  '__init__.py',
  'main.py',
  'application.py',
  'logging_util.py',
  'window.py',
  'backend.py',
  'brew_env.py',
  'package.py',
  'taps.py',
  'media.py',
  'backend_icons.py',
  'git_forge.py',
  'package_tile.py',
  'package_details.py',
  'search_page.py',
  'browse_page.py',
  'installed_page.py',
  'tap_page.py',
  'task_manager.py',
  'task_panel.py',
  'global_progress.py',
  'brewfile_dialog.py',
  'brewfile_page.py',
  'search_provider.py',
  'updates_card.py',
  'version_history_dialog.py',
  'screenshot_lightbox.py',
  'stats_dialog.py',
]

install_data(tavern_sources, install_dir: pkgdatadir / 'tavern')

install_data(
  'shell-search-provider-dbus-interfaces.xml',
  install_dir: pkgdatadir
)
