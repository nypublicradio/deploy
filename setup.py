"""
NYPR Deployment CLI Utility
"""

from setuptools import setup

setup(
    name='nypr.deploy',
    version='0.0.5',
    author='NYPR Digital',
    author_email='digitalops@nypublicradio.org',
    url='https://github.com/nypublicradio/deploy',
    description='cli tool for replicatable deployments',
    long_description=__doc__,
    packages=[
        'deploy',
        'deploy.ecs',
    ],
    package_dir={
        'deploy': 'deploy',
    },
    zip_safe=True,
    license='BSD',
    install_requires=[
        'boto3',
        'docker',
        'docopt'
    ],
    scripts=[
        'scripts/ecs_deploy'
    ],
    test_suite='nose.collector',
    tests_require=['nose']
)
