"""Required Environment Variables:

AWS_ACCOUNT_ID:     The id number for the target AWS account.

AWS_ECS_CLUSTER:    The basename of the target ECS cluster.
                    This should *not* include env or the "-cluster" suffix.
                    eg. Good: "http", Bad: "http-prod-cluster"

AWS_DEFAULT_REGION: The AWS region of the ECS cluster.
                    eg. us-east-1

CIRCLE_TAG
or
CIRCLE_SHA1:        Either the release tag from GitHub (preferred) or the
                    sha1 hash of the CircleCI build. This value is used to
                    tag the build of the docker image. The BUILD_TAG value
                    is derived from the preferred variable here.

CIRCLE_PROJECT_REPONAME: The name of the project's GitHub repository.
"""
import inspect
import os


class UnsetEnvironmentVariable(Exception):
    def __init__(self, var_name, *args, **kwargs):
        template = "Unset environment variable {}.\n\n{}"
        message = template.format(var_name, __doc__)
        super().__init__(message, *args, **kwargs)


def load_deploy_ini(filename='deploy.ini'):
    import configparser
    config = configparser.ConfigParser()
    config.optionxform = str
    if os.path.isfile(filename):
        config.read(filename)
        return config
    else:
        config.add_section('deploy')


deploy_ini = load_deploy_ini()


def get_env_var(upper_arg_name):
    """ arg_name: str
        -> str
        Returns the value of an environment variable from a string.
        BUILD_TAG is a special case that will be populated by CIRCLE_TAG
        or CIRCLE_SHA1, depending on which is available.
        Preference to is given to CIRCLE_TAG which is the value of a git
        tag.
    """
    if upper_arg_name == 'BUILD_TAG':
        env_var = os.environ.get('CIRCLE_TAG', os.environ.get('CIRCLE_SHA1'))
        if not env_var:
            raise UnsetEnvironmentVariable('CIRCLE_TAG or CIRCLE_SHA1')
    else:
        env_var = os.environ.get(upper_arg_name)
    if env_var:
        return env_var
    else:
        raise UnsetEnvironmentVariable(upper_arg_name)


def with_defaults(func):
    """ Wraps a function and fills any missing arguments
        with the value of a corresponding environment variable.
        eg. an unset aws_region will take the values of AWS_REGION
    """

    def wraps(*args, **kwargs):
        argspec = inspect.getargspec(func)
        arg_names = argspec.args[len(args):]
        unset_args = [s for s in arg_names if s not in kwargs.keys()]

        for unset_arg in unset_args:
            upper_arg_name = unset_arg.upper()
            kwargs[unset_arg] = (deploy_ini['deploy'].get(upper_arg_name)
                                 or get_env_var(upper_arg_name))

        return func(*args, **kwargs)
    return wraps
