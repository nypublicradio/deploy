import os
import shlex
import sys
from contextlib import contextmanager
from setuptools import Command
from setuptools.command.test import test as TestCommand


@contextmanager
def cov():
    import coverage
    cov = coverage.Coverage()
    cov.start()
    yield
    cov.stop()
    cov.save()
    report = cov.report()
    if cov.config.fail_under >= report:
        sys.exit('Minimum code coverage {}% not met.'
                 .format(cov.config.fail_under))


class InstallRequirements(Command):
    description = ('Installs package dependencies as if they were installed '
                   'using "pip install -r requirements.txt". This is useful '
                   'for caching third-party packages in Docker images.')
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        import pip
        install_from_git = [pkg.split('=')[:len('#egg=')] for pkg
                            in self.distribution.dependency_links]
        install_from_pypi = [pkg for pkg in self.distribution.install_requires
                             if pkg not in install_from_git]
        pip.main(['install'] + self.distribution.dependency_links + install_from_pypi)


class DjangoTest(TestCommand):
    description = 'Tests package with Django test runner and coverage.'
    user_options = [
        ('additional-test-args=', 'a', 'Arguments to pass to test suite.'),
        ('django-settings=', 'f', 'Django settings file to load for tests.'),
    ]

    def _set_django_settings_environment(self):
        """ If the --django-settings argument is not provided this command
            will attempt to retrieve the value from the manage.py file.
            This can fail if manage.py has been modified and no longer
            contains the os.environ.setdefault command in a single line.
        """
        if self.django_settings:
            os.environ['DJANGO_SETTINGS_MODULE'] = self.django_settings
        else:
            import re
            pattern = re.compile(
                r'^os\.environ\.setdefault\(["\']DJANGO_SETTINGS_MODULE["\'], '
                r'["\'](?P<module>[^"\']+)["\']\)$'
            )
            try:
                with open('manage.py', 'r') as f:
                    for match in (pattern.match(line.strip()) for line in f):
                        if match:
                            module = match.groupdict()['module']
                            os.environ['DJANGO_SETTINGS_MODULE'] = module
                            break
                    else:
                        raise IOError
            except IOError:
                sys.exit('Must provide --django-settings argument.')

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.additional_test_args = ''
        self.django_settings = None

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        self._set_django_settings_environment()
        import django
        from django.test.utils import get_runner
        from django.conf import settings
        django.setup()

        args = shlex.split(self.additional_test_args) + self.test_args

        with cov():
            TestRunner = get_runner(settings)
            test_runner = TestRunner(verbosity=1, interactive=True)
            failures = test_runner.run_tests(args)

        if bool(failures):
            sys.exit(1)


class PyTest(TestCommand):
    description = 'Tests package with pytest.'
    user_options = [
        ('additional-test-args=', 'a', 'Arguments to pass to test suite.')
    ]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.additional_test_args = ''

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        args = shlex.split(self.pytest_args) + self.test_args
        exit_code = pytest.main(args)
        sys.exit(exit_code)
