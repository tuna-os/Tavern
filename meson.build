project('tavern',
  version: '0.1.15',
  # Version 0.1.9 release
  meson_version: '>= 1.0.0',
  default_options: [
    'warning_level=2',
  ],
)

i18n = import('i18n')
gnome = import('gnome')
python = import('python')

py_installation = python.find_installation('python3')

dependency('gtk4', version: '>= 4.12')
dependency('libadwaita-1', version: '>= 1.4')

APPLICATION_ID = 'dev.hanthor.Tavern'
PKGDATADIR = get_option('prefix') / get_option('datadir') / meson.project_name()

conf = configuration_data()
conf.set('APPLICATION_ID', APPLICATION_ID)
conf.set('VERSION', meson.project_version())
conf.set('PKGDATADIR', PKGDATADIR)
conf.set('PYTHON', py_installation.full_path())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('prefix', get_option('prefix'))

subdir('data')
subdir('src')
subdir('po')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
