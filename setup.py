from setuptools import setup

setup(name='sure_petcare',
      version='0.1',
      description='Library to access sure connect catflat',
      url='http://github.com/rcastberg/sure_petcare',
      author='Rene Castberg',
      author_email='rene@castberg.org',
      license='GPL',
      install_requires=['requests'],
      packages=['sure_petcare'],
      scripts=['sp_cli.py'],
      zip_safe=False)
