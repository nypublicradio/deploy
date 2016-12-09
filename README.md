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
  ecs_deploy build
  ecs_deploy test
  ecs_deploy deploy --env=<env> --memory-reservation=<kb>
                    [--memory-reservation-hard] [--cpu=<num>]
                    [--port=<port> ...] [--timeout=<seconds>]

Options:
  -h --help                     Show this screen.
  --version                     Show version.
  --env=<env>                   Environment (eg. dev|demo|prod|util)
  --memory-reservation=<kb>     Memory reservation size for container in KB.
  --memory-reservation-hard     Flag to set memory reservation to a hard
                                reservation.
  --cpu=<num>                   CPU credit limit for container.
  --port=<port>                 Repeatable, ports for the container to expose.
  --timeout=<seconds>           How long to wait for old ECS services to stop.
                                [default: 300]
```

#### Circle Example
```
machine:
  services:
    - docker
  python:
    version: 3.5.2

dependencies:
  override:
    - pip3 install -U git@github.com:nypublicradio/deploy
    - ecs_deploy build

test:
  override:
    - ecs_deploy test

deployment:
  prod:
    tag: /v[0-9]+\.[0-9]+\.[0-9]+/
    commands:
      - ecs_deploy deploy --env prod --memory-reservation=2048 --port 8080

  demo:
    branch: master
    commands:
      - ecs_deploy deploy --env demo --memory-reservation=1024 --port 8080
```

#### Required Environment Variables
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
