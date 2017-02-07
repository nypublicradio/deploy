# NYPR CLI Deployment Utility

## Installation

```bash
pip install git+https://github.com/nypublicradio/deploy.git
```

## Deployment Types

### ECS Deploy

#### Usage
```
 NYPR ECS Deployment Tool.

Usage:
  ecs_deploy build  [--build-tag=<tag>] [--no-use-cache] [--with-circle-hack]
  ecs_deploy test   [--build-tag=<tag>] [--test-cmd=<cmd>]
  ecs_deploy deploy --env=<env> --memory-reservation=<kb>
                    [--build-tag=<tag>] [--no-service]
                    [--memory-reservation-hard] [--cpu=<num>]
                    [--port=<port> ...] [--timeout=<seconds>]
                    [(--cmd=<cmd> --role=<role>)]
  ecs_deploy cleanup --env=<env> --revisions-to-keep=<num> [--role=<role>]

Options:
  -h --help                     Show this screen.
  --version                     Show version.
  --build-tag=<tag>             Manually specify a build tag.

  # build
  --no-use-cache                Do not use cached files.
  --with-circle-hack            Splits the Dockerfile at the requirements
                                installation step to avoid re-building
                                virtualenvrionments unless setup.py changes.

  # test
  --test-cmd=<cmd>              Test command [default: python setup.py test]

  # deploy
  --env=<env>                   Environment (eg. dev|demo|prod|util)
  --memory-reservation=<kb>     Memory reservation size for container in KB.
  --no-service                  Flag to set non-persistent task.
  --memory-reservation-hard     Flag to set memory reservation to a hard.
  --cpu=<num>                   CPU credit limit for container.
  --port=<port>                 Port for the container to expose.
  --timeout=<seconds>           How long to wait for old ECS services to stop.
                                [default: 300]
  --cmd=<cmd>                   Command override for ECS task, specified
                                as a comma-delimited string.
  --role=<role>                 Must be provided if --cmd is provided,
                                used to distinguish between tasks/services
                                for repos that require multiple containers to
                                run (eg. a worker and web interface).

  # cleanup
  --revisions-to-keep=<num>     How many previous task definitions to preserve
```

#### Circle Example (Single Service)
This example will produce a single service and task definition
named after the project's repo and deployment environment (eg. auth-prod).
```
machine:
  services:
    - docker
  python:
    version: 3.6.0

dependencies:
  cache_directories:
    - "~/docker"
  override:
    - pip3 install -U git+https://github.com/nypublicradio/deploy.git
    - ecs_deploy build

test:
  override:
    - ecs_deploy test

deployment:
  prod:
    tag: /v[0-9]+\.[0-9]+\.[0-9]+/
    commands:
      - ecs_deploy deploy --env=prod --memory-reservation=2048 --port=8080

  demo:
    branch: master
    commands:
      - ecs_deploy deploy --env=demo --memory-reservation=1024 --port=8080
```

#### Circle Example (Two Services)

This example will produce two services and two task definitions, named after
the project's repo, deployment environment, and individual roles
(eg. auth-prod-web and auth-prod-worker).
```
machine:
  services:
    - docker
  python:
    version: 3.5.2

dependencies:
  cache_directories:
    - "~/docker"
  override:
    - pip3 install -U git+https://github.com/nypublicradio/deploy.git
    - ecs_deploy build

test:
  override:
    - ecs_deploy test

deployment:
  prod:
    tag: /v[0-9]+\.[0-9]+\.[0-9]+/
    commands:
      - ecs_deploy deploy --env=prod --memory-reservation=2048 --port=8080 --cmd=run_webserver,-p,8080 --role=web
      - ecs_deploy deploy --env=prod --memory-reservation=1024 --cmd=run_worker --role=worker

  demo:
    branch: master
    commands:
      - ecs_deploy deploy --env=demo --memory-reservation=1024 --port=8080 --cmd=run_webserver,-p,8080 --role=web
      - ecs_deploy deploy --env=demo --memory-reservation=512 --cmd=run_worker --role=worker
```

#### Required Environment Variables
See **Running Manual Deployments** at the bottom of this document as an
alternative to setting environment variables.
```
Required Environment Variables:

AWS_ACCOUNT_ID:     The id number for the target AWS account.

AWS_ECS_CLUSTER:    The basename of the target ECS cluster.
                    This should *not* include env or the "-cluster" suffix.
                    eg. Good: "http", Bad: "http-prod-cluster"

AWS_DEFAULT_REGION: The AWS region of the ECS cluster.
                    eg. us-east-1

CIRCLE_TAG or
CIRCLE_SHA1:        Either the release tag from GitHub (preferred) or the
                    sha1 hash of the CircleCI build. This value is used to
                    tag the build of the docker image. The BUILD_TAG value
                    is derived from the preferred variable here.

CIRCLE_PROJECT_REPONAME: The name of the project's GitHub repository.
```

#### Adding Task Environment Variables
Any CircleCI environment variable prefixed with `<ENV>_` will be passed to the
task definition without the `<ENV>_` prefix.
eg. A variable `PROD_AWS_SECRET_ACCESS_KEY` would be included in the task
definition as `AWS_SECRET_ACCESS_KEY`.


#### Running Manual Deployments
Sometimes a developer with sufficient permissions may need to bypass the
CircleCI process to run deployments manually. In these cases it is best to
create a `deploy.ini` in the root of the repository one wishes to build
and deploy (make sure this file is in the `.gitignore`). The `deploy.ini` file
should follow the format below. The `[deploy]` section includes information
about the environment that will be deployed to. The `[demo]` and `[prod]`
sections should include any environment variables that need to be copied into
the task definitions of deployed tasks/services. In CircleCI the equivalent
variables are those prefixed with `PROD_` or `DEMO_`.
```
[deploy]
AWS_ACCOUNT_ID=<acct_id>
AWS_ECS_CLUSTER=<cluster_name>
AWS_DEFAULT_REGION=us-east-1
CIRCLE_PROJECT_REPONAME=<git_repo_name>

[demo]
ENV_VAR_1=
ENV_VAR_2=

[prod]
ENV_VAR_1=
ENV_VAR_2=
```
