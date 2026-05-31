desktop_file = i18n.merge_file(
  input: 'dev.hanthor.Tavern.desktop.in',
  output: 'dev.hanthor.Tavern.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

appstream_file = i18n.merge_file(
  input: 'dev.hanthor.Tavern.metainfo.xml.in',
  output: 'dev.hanthor.Tavern.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

install_data(
  'dev.hanthor.Tavern.gschema.xml',
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

install_data(
  'dev.hanthor.Tavern-mime.xml',
  install_dir: get_option('datadir') / 'mime' / 'packages',
)

install_data(
  'icons/hicolor/scalable/apps/dev.hanthor.Tavern.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

install_data(
  'icons/hicolor/symbolic/apps/dev.hanthor.Tavern-symbolic.svg',
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)
install_data(
  'dev.hanthor.Tavern.search-provider.ini.in',
  rename: 'dev.hanthor.Tavern.search-provider.ini',
  install_dir: get_option('datadir') / 'gnome-shell' / 'search-providers'
)

service_conf = configuration_data()
service_conf.set('bindir', get_option('prefix') / get_option('bindir'))
configure_file(
  input: 'dev.hanthor.Tavern.service.in',
  output: 'dev.hanthor.Tavern.service',
  configuration: service_conf,
  install_dir: get_option('datadir') / 'dbus-1' / 'services'
)

# ── Validation ────────────────────────────────────────────────────────────────
desktop_file_validate = find_program('desktop-file-validate', required: false)
if desktop_file_validate.found()
  test('Validate desktop file',
    desktop_file_validate,
    args: [desktop_file],
  )
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('Validate appstream file',
    appstreamcli,
    args: ['validate', '--no-net', appstream_file],
  )
endif
