import boto3
import docker
import os
import time

from base64 import b64decode
from .settings import with_defaults


def get_docker_image_url(aws_account_id, aws_default_region,
                         circle_project_reponame, build_tag):
    """ aws_account_id: str
        aws_default_region: str
        circle_project_reponame: str
        build_tag: str
        -> docker_img: str

        Returns a url of a docker image constructed from the name of a github
        repository, a build tag (eg. GitHub release tag or CircleCI SHA1), and
        some AWS account information.
    """
    ecr_url = '{}.dkr.ecr.{}.amazonaws.com'.format(aws_account_id,
                                                   aws_default_region)
    docker_img = '{}/{}:{}'.format(ecr_url, circle_project_reponame, build_tag)
    return docker_img


def get_ecs_task_name(circle_project_reponame, env):
    """ circle_project_reponame: str
        env: str
        -> task_name: str

        Returns the task name of an ECS task in the format <repo>-<env>.
    """
    task_name = '{}-{}'.format(circle_project_reponame, env)
    return task_name


def get_ecs_task_environment_vars(env):
    """ env: str
        -> List[Dict]
    """
    match_prefix = '{}_'.format(env.upper())

    def strip_prefix(s): s[len(match_prefix):]  # strips <ENV>_ from name

    env_var_defs = []
    for env_var_name, env_var_val in os.environ.items():
        if env_var_name.startswith(match_prefix):
            stripped_env_var_name = strip_prefix(env_var_name)
            env_var_def = {'name': stripped_env_var_name, 'value': env_var_val}
            env_var_defs.append(env_var_def)


def get_ecs_cluster_name(aws_ecs_cluster, env):
    """ aws_ecs_cluster: str
        env: str
        -> ecs_cluster: str
    """
    ecs_cluster = '{}-{}-cluster'.format(aws_ecs_cluster, env)
    return ecs_cluster


class ECSServiceUpdateError(Exception):
    pass


class ECSDeploy():

    @with_defaults
    def __init__(self,
                 aws_account_id=None,
                 aws_ecs_cluster=None,
                 aws_default_region=None,
                 build_tag=None,
                 circle_project_reponame=None,
                 env=None,
                 test_command='python setup.py test'):
        self.docker_client = docker.Client(version='1.21')
        self.test_command = test_command
        self.docker_img_url = get_docker_image_url(aws_account_id,
                                                   aws_default_region,
                                                   circle_project_reponame,
                                                   build_tag)
        self.ecs_task_name = get_ecs_task_name(circle_project_reponame, env)
        self.ecs_task_env_vars = get_ecs_task_environment_vars(env)
        self.ecs_cluster_name = get_ecs_cluster_name(aws_ecs_cluster, env)

    def build_docker_img(self):
        self.docker_client.build('.', tag=self.docker_img_url)

    def test_docker_img(self):
        self.docker_client.excute(self.docker_img_url, self.test_command)

    def get_task_def(self, memory_reservation, cpu=None,
                     memory_reservation_hard=False, ports=None):
        """ Returns a JSON task template that will be uploaded to ECS
            to create a new task version. Any environment variable prefixed
            with ENV_ will be accessible to the container running the task.
        """
        task_def = {
            'name': self.ecs_task_name,
            'image': self.docker_img_url,
            'essential': True,
            'environment': self.ecs_task_env_vars
        }

        # Task defs require a soft or hard memory reservation to be set
        if memory_reservation_hard:
            task_def['memory'] = memory_reservation
        else:
            task_def['memoryReservation'] = memory_reservation

        if cpu:
            task_def['cpu'] = cpu

        if ports:
            task_def['portMappings'] = [{'containerPort': p} for p in ports]

        return task_def

    def push_ecr_image(self):
        """ Utilizes the AWS ECR authorization token to perform a docker
            registry login and push the built image.
        """
        ecr = boto3.client('ecr')
        resp = ecr.get_authorization_token()
        auth_data = resp['authorizationData'][0]

        # The boto3 API returns the authorizationToken as a base64encoded
        # string which contains the username and password for auth.
        auth_token = b64decode(auth_data['authorizationToken']).decode()
        username, password = auth_token.split(':')

        self.docker_client.login(
            username=username,
            password=password,
            email='none',
            registry=auth_data['proxyEndpoint']
        )

        # On the cli we'd use "docker push repo:tag"
        # but here they need to be split.
        repository, tag = self.docker_image_url.split(':')
        self.docker_client.push(
            repository=repository,
            tag=tag
        )

    def register_task_def(self, task_def):
        """ Utilizes the boto3 library to register a task definition
            with AWS.
        """
        family = self.ecs_task_name
        client = boto3.client('ecs')
        resp = client.register_task_definition(
            containerDefinitions=[
                task_def
            ],
            family=family
        )
        revision = resp['taskDefinition']['taskDefinitionArn']
        return revision

    def update_ecs_service(self, task_def_revision, timeout):
        service = self.ecs_task_name
        cluster = self.ecs_cluster_name

        client = boto3.client('ecs')
        resp = client.update_service(
            service=service,
            cluster=cluster,
            taskDefinition=task_def_revision
        )

        if resp['service']['taskDefintion'] != task_def_revision:
            raise ECSServiceUpdateError('Error updating ECS service:'
                                        '\n{}'.format(resp))

        timer = 0
        timer_increment = 10
        stale = True
        while (timer < timeout and stale):
            resp = client.describe_services(
                services=[
                    service
                ],
                cluster=cluster
            )
            deployments = resp['services'][0]['deployments']
            stale_deployments = [d for d in deployments
                                 if d['taskDefinition'] != task_def_revision]
            if len(stale_deployments):
                for d in stale_deployments:
                    msg = '[{}/{}]'.format(timer, timeout)
                    msg += 'Waiting on {runningCount} containers ' \
                           '{taskDefinition} to stop.'.format(**d)
                    print(msg)
                stale = True
            else:
                print('Stale containers stopped, deployment complete.')
                stale = False
            timer += timer_increment
            time.sleep(timer_increment)

    def deploy(self, memory_reservation, cpu=None,
               memory_reservation_hard=False, ports=None, timeout=300):
        task_def = self.get_task_def(memory_reservation,
                                     cpu,
                                     memory_reservation_hard,
                                     ports)
        task_def_revision = self.register_task_def(task_def)
        self.update_ecs_service(task_def_revision, timeout)
