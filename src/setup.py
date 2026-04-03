from setuptools import setup
import setup_translate

pkg = 'Extensions.SHOUTcast'
setup(name='enigma2-plugin-extensions-shoutcast',
       version='3.0',
       description='A client to listen and record SHOUTcast internet radio',
       package_dir={pkg: 'SHOUTcast'},
       packages=[pkg],
       package_data={pkg: ['images/*.png', '*.png', '*.xml', 'locale/*/LC_MESSAGES/*.mo', 'maintainer.info', 'plugin.png', 'shoutcast-logo1-fs8.png', 'favorites']},
       cmdclass=setup_translate.cmdclass,  # for translation
      )
