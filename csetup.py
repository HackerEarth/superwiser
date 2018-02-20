from setuptools import setup

setup(name='he-superwiser-client',
      version='0.2',
      description='Client to run on each supervisor machine',
      url='https://github.com/farthVader91/superwiser/',
      author='Vishal Gowda',
      author_email='cartmanboy1991@gmail.com',
      license='GPL',
      install_requires=[
          'kazoo==2.2.1',
          'supervisor==3.3.1',
          'Twisted==17.1.0',
      ],
      packages=[
          'superwiser',
          'superwiser.common',
          'superwiser.toolchain',
      ],
      entry_points={
        'console_scripts': [
            'orcd = superwiser.toolchain.mainloop:start_loop'],
      },
      package_data={
          'superwiser.toolchain': ['template.conf'],
      },
      zip_safe=False)
