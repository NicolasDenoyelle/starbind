###############################################################################
# Copyright 2020 UChicago Argonne, LLC.
# (c.f. AUTHORS, LICENSE)
# For more info, see https://xgitlab.cels.anl.gov/argo/cobalt-python-wrapper
# SPDX-License-Identifier: BSD-3-Clause
##############################################################################

from setuptools import setup

setup(name='starbind',
      version='0.1',
      description='HPC Application launcher with process/thread binding.',
      url='',
      author='Nicolas Denoyelle',
      author_email='ndenoyelle@anl.gov',
      license='BSD-3-Clause',
      packages=['starbind'],
      python_requires='>=3.0',
      install_requires=['tmap'],
      zip_safe=False)

