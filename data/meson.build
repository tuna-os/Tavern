desktop_file = i18n.merge_file(
  input: configure_file(
    input: 'org.tunaos.tavern.desktop.in',
    output: '@0@.desktop.in'.format(APPLICATION_ID),
    configuration: conf,
  ),
  output: '@0@.desktop'.format(APPLICATION_ID),
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

appstream_file = i18n.merge_file(
  input: configure_file(
    input: 'org.tunaos.tavern.metainfo.xml.in',
    output: '@0@.metainfo.xml.in'.format(APPLICATION_ID),
    configuration: conf,
  ),
  output: '@0@.metainfo.xml'.format(APPLICATION_ID),
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

configure_file(
  input: 'org.tunaos.tavern.gschema.xml.in',
  output: '@0@.gschema.xml'.format(APPLICATION_ID),
  configuration: conf,
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

install_data(
  'org.tunaos.tavern-mime.xml',
  rename: '@0@-mime.xml'.format(APPLICATION_ID),
  install_dir: get_option('datadir') / 'mime' / 'packages',
)

icon_suffix = ''
if profile == 'development'
  icon_suffix = '.Devel'
endif

install_data(
  'icons/hicolor/scalable/apps/org.tunaos.tavern@0@.svg'.format(icon_suffix),
  rename: '@0@.svg'.format(APPLICATION_ID),
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'scalable' / 'apps',
)

install_data(
  'icons/hicolor/symbolic/apps/org.tunaos.tavern@0@-symbolic.svg'.format(icon_suffix),
  rename: '@0@-symbolic.svg'.format(APPLICATION_ID),
  install_dir: get_option('datadir') / 'icons' / 'hicolor' / 'symbolic' / 'apps',
)

configure_file(
  input: 'org.tunaos.tavern.search-provider.ini.in',
  output: '@0@.search-provider.ini'.format(APPLICATION_ID),
  configuration: conf,
  install_dir: get_option('datadir') / 'gnome-shell' / 'search-providers'
)

service_conf = configuration_data()
service_conf.set('bindir', get_option('prefix') / get_option('bindir'))
service_conf.set('APPLICATION_ID', APPLICATION_ID)
configure_file(
  input: 'org.tunaos.tavern.service.in',
  output: '@0@.service'.format(APPLICATION_ID),
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
