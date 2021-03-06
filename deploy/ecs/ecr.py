import boto3
import docker
import json
import os
import sys
import time

from base64 import b64decode
from .settings import with_defaults, deploy_ini


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


def get_ecs_task_name(circle_project_reponame, env, role=None):
    """ circle_project_reponame: str
        env: str
        -> task_name: str

        Returns the task name of an ECS task in the format <repo>-<env>.
        Optionally, a role can distinguish the task <repo>-<env>-<role>.
    """
    task_basename = '{}-{}'.format(circle_project_reponame, env)
    if role:
        task_name = '{}-{}'.format(task_basename, role)
    else:
        task_name = task_basename
    return task_name


def get_ecs_task_environment_vars(env):
    """ env: str
        -> List[Dict]
    """
    match_prefix = '{}_'.format(env.upper())

    def strip_prefix(s):
        return s[len(match_prefix):]  # strips <ENV>_ from name

    env_var_defs = [{'name': 'ENV', 'value': env}]
    for env_var_name, env_var_val in os.environ.items():
        if env_var_name.startswith(match_prefix):
            stripped_env_var_name = strip_prefix(env_var_name)
            env_var_def = {'name': stripped_env_var_name, 'value': env_var_val}
            env_var_defs.append(env_var_def)

    if deploy_ini.has_section(env):
        for env_var_name, env_var_val in deploy_ini[env].items():
            env_var_def = {'name': env_var_name, 'value': env_var_val}
            env_var_defs.append(env_var_def)
    return env_var_defs


def backup_secrets(circle_project_reponame, s3_bucket):
    """ s3_bucket: str
        -> Dict
    """
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucket)
    s3_key = '{}.json'.format(circle_project_reponame)
    secrets = {
        'demo': [],
        'prod': []
    }
    for env in secrets.keys():
        secrets[env] = get_ecs_task_environment_vars(env)
    json_blob = bytes(json.dumps(secrets), 'utf-8')
    bucket.put_object(
        ACL='private',
        Body=json_blob,
        ContentEncoding='utf-8',
        ContentType='application/json',
        Key=s3_key
    )


def get_ecs_cluster_name(aws_ecs_cluster, env):
    """ aws_ecs_cluster: str
        env: str
        -> ecs_cluster: str
    """
    ecs_cluster = '{}-{}-cluster'.format(aws_ecs_cluster, env)
    return ecs_cluster


def get_ecs_log_group_name(aws_ecs_cluster, env):
    """ aws_ecs_cluster: str
        env: str
        -> ecs_log_group_name: str
    """
    ecs_log_group_name = '{}-{}/services'.format(aws_ecs_cluster, env)
    return ecs_log_group_name


def pprint_docker(byte_msg):
    """ byte_msg: bytes
        -> None
    """
    str_msg = byte_msg.decode()
    d = json.loads(str_msg)
    if 'stream' in d:
        msg = d['stream']
    elif 'status' in d:
        if d.get('progressDetail'):
            status = d.get('status', '')
            current = d['progressDetail'].get('current', '')
            total = d['progressDetail'].get('total', '')
            id_ = d.get('id', '')
            progress = d.get('progress', '')
            msg = '{} ({}/{}) {} {}'.format(status, current, total,
                                            id_, progress)
        else:
            msg = d['status']
    else:
        msg = str_msg
    print(msg)


class ECSServiceUpdateError(Exception):
    pass


class ContainerTestError(Exception):
    pass


class MissingRoleError(Exception):
    pass


class ECSDeploy():

    @with_defaults
    def __init__(self,
                 aws_account_id=None,
                 aws_ecs_cluster=None,
                 aws_default_region=None,
                 build_tag=None,
                 circle_project_reponame=None):
        self.docker_client = docker.from_env(version='1.21')
        self.docker_img_url = get_docker_image_url(aws_account_id,
                                                   aws_default_region,
                                                   circle_project_reponame,
                                                   build_tag)
        self.reponame = circle_project_reponame
        self.ecs_cluster_basename = aws_ecs_cluster
        self.aws_default_region = aws_default_region
        self.aws_account_id = aws_account_id
        self.partial_tag = '{}:partial'.format(circle_project_reponame)

    def load_docker_cache(self, cache_dir):
        """ cache_dir: str
        -> None
        Loads all saved docker images from a given directory.
        """
        for root, dirname, files in os.walk(cache_dir):
            for filename in files:
                file_path = os.path.join(root, filename)
                with open(file_path, 'rb') as f:
                    print('Loading cached image {}'.format(file_path))
                    self.docker_client.images.load(f)

    def get_base_image_from_dockerfile(self):
        """
        -> HTTPResponse
        Returns an HTTPReponse object.
        The .data property of this object contains the binary data of an image.
        The image is selected based on the FROM... line of a Dockerfile.
        """
        with open('Dockerfile', 'r') as f:
            for line in f:
                if line.startswith('FROM '):
                    _, base_image_name = line.strip().split(' ', 1)
                    break
            else:
                print('Did not find FROM block in Dockerfile.')
                return
        try:
            base_image = self.docker_client.api.get_image(base_image_name)
        except docker.errors.ImageNotFound:
            print('Did not find image {}.'.format(base_image_name))
            base_image = None
        return base_image

    def get_new_image(self):
        """
        -> HTTPResponse
        Returns an HTTPResponse object.
        The .data property of this object contains the binary data of an image.
        The image is selected based on the repo/tag of the current build.
        """
        try:
            new_image = self.docker_client.api.get_image(self.docker_img_url)
        except docker.errors.ImageNotFound:
            print('Did not find image {}.'.format(self.docker_img_url))
            new_image = None
        return new_image

    def get_partial_image(self):
        """
        -> HTTPResponse
        Returns an HTTPResponse object.
        The .data property of this object contains the binary data of an image.
        The image is selected based on the partial image tag.
        This only returns when images are built with --with-circle-hack flag.
        """
        try:
            partial_image = self.docker_client.api.get_image(self.partial_tag)
        except docker.errors.ImageNotFound:
            print('Did not find image {}.'.format(self.partial_tag))
            partial_image = None
        return partial_image

    def save_docker_cache(self, cache_dir, with_circle_hack):
        """ cache_dir: str
        -> None
        Saves base image and completed image to the cache_dir.
        Each image is acquired using the low-level docker.api.get_image method
        so that tags are preserved when saving.
        """
        base_image = self.get_base_image_from_dockerfile()
        new_image = self.get_new_image()
        images = [(base_image, 'base.tar'), (new_image, 'image.tar')]
        if with_circle_hack:
            partial_image = self.get_partial_image()
            images.append((partial_image, 'partial.tar'))
        for image, cache_file_name in images:
            cache_file = os.path.join(cache_dir, cache_file_name)
            with open(cache_file, 'wb') as f:
                print('Saving image cache at {}'.format(cache_file))
                f.write(image.data)

    def hack_dockerfile(self):
        """
        CircleCI uses a filesystem that prevents access to intermediate
        Docker containers. This presents a problem when caching because
        we can only cache the base & final images; if dependencies are
        installed somewhere in the middle they must be installed every build.
        This is an ugly hack to split the Dockerfile at our custom
        `python setup.py requirements` stage, creating an intermediate
        container "<reponame>:partial" that will be cached.
        """
        import tarfile
        from io import BytesIO

        ignore_list = [
            '.git',
            '.cache'
        ]

        def ignore(filename):
            if any(s in filename for s in ignore_list):
                return True
            else:
                return False

        def build(dockerfile_str, build_tag):
            dockerfile = BytesIO()
            dockerfile.write(dockerfile_str.encode('utf-8'))
            dockerfile.seek(0)

            tar_fileobj = BytesIO()
            with tarfile.open(fileobj=tar_fileobj, mode='w') as tar:
                tar.add('.', recursive=True, exclude=ignore)
                tar_info = tar.getmember('./Dockerfile')
                tar_info.size = dockerfile.getbuffer().nbytes
                tar.addfile(tar_info, dockerfile)
            tar_fileobj.seek(0)

            for line in self.docker_client.api.build(fileobj=tar_fileobj,
                                                     custom_context=True,
                                                     rm=False,
                                                     tag=build_tag):
                pprint_docker(line)

        def split_dockerfile():
            partial_container = ''
            full_container = 'FROM {}\n'.format(self.partial_tag)
            with open('Dockerfile', 'r') as f:
                for line in f:
                    if 'python setup.py requirements' not in line:
                        partial_container += line
                    else:
                        partial_container += line
                        break
                for line in f:
                    full_container += line
            return partial_container, full_container

        partial_dockerfile_str, full_dockerfile_str = split_dockerfile()
        build(partial_dockerfile_str, self.partial_tag)
        build(full_dockerfile_str, self.docker_img_url)

    def build_docker_img(self, no_use_cache=False, with_circle_hack=False):
        if not no_use_cache:
            cache_dir = os.path.join(os.path.expanduser('~'), 'docker')
            os.makedirs(cache_dir, exist_ok=True)
            self.load_docker_cache(cache_dir)

        if with_circle_hack:
            self.hack_dockerfile()
        else:
            for line in self.docker_client.api.build(path='.', rm=False,
                                                     tag=self.docker_img_url):

                pprint_docker(line)

        if not no_use_cache:
            self.save_docker_cache(cache_dir, with_circle_hack)

    def test_docker_img(self, test_command):
        if not test_command:
            raise ContainerTestError('Test command cannot be empty.')
        try:
            log = self.docker_client.containers.run(
                image=self.docker_img_url,
                command=test_command,
                detach=False,
                stdout=True,
                stderr=True
            )
            print(log.decode())
        except docker.errors.ContainerError as e:
            print(e)
            sys.exit('Tests Failed')
        print('Tests Passed')
        sys.exit(0)

    def get_task_def(self, env, memory_reservation, cpu=None,
                     memory_reservation_hard=False, ports=None,
                     cmd=None, role=None):
        """ Returns a JSON task template that will be uploaded to ECS
            to create a new task version. Any environment variable prefixed
            with ENV_ will be accessible to the container running the task.
        """
        if cmd and not role:
            raise MissingRoleError('Cannot specify cmd override without role.')
        ecs_task_name = get_ecs_task_name(self.reponame, env, role)
        ecs_task_env_vars = get_ecs_task_environment_vars(env)
        ecs_log_group_name = get_ecs_log_group_name(self.ecs_cluster_basename,
                                                    env)
        task_def = {
            'name': ecs_task_name,
            'image': self.docker_img_url,
            'essential': True,
            'environment': ecs_task_env_vars,
            'logConfiguration': {
                'logDriver': 'awslogs',
                'options': {
                    'awslogs-group': ecs_log_group_name,
                    'awslogs-region': self.aws_default_region,
                    'awslogs-stream-prefix': ecs_task_name
                }
            }
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

        if cmd:
            task_def['command'] = cmd

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
        repo, tag = self.docker_img_url.split(':')
        for line in self.docker_client.api.push(repository=repo, tag=tag,
                                                stream=True):
            pprint_docker(line)

    def register_task_def(self, env, task_def, role=None):
        """ Utilizes the boto3 library to register a task definition
            with AWS.
        """
        family = get_ecs_task_name(self.reponame, env, role)
        client = boto3.client('ecs')
        resp = client.register_task_definition(
            containerDefinitions=[
                task_def
            ],
            family=family
        )
        revision = resp['taskDefinition']['taskDefinitionArn']
        return revision

    def deregister_task_defs(self, env, revisions_to_keep, role=None):
        """ env: str
            revisions_to_keep: int

            revisions_to_keep is an integer that represents how many
            previous revisions should be preserved.
        """
        client = boto3.client('ecs')
        family = get_ecs_task_name(self.reponame, env, role)
        task_def_arns = client.list_task_definitions(
            familyPrefix=family
        )['taskDefinitionArns']
        task_def_arns_to_deregister = task_def_arns[:-revisions_to_keep]
        for task_def_arn in task_def_arns_to_deregister:
            resp = client.deregister_task_definition(
                taskDefinition=task_def_arn
            )
            deregistered_arn = resp['taskDefinition']['taskDefinitionArn']
            print('Deregistered task: {}'.format(deregistered_arn))

    def update_ecs_service(self, env, task_def_revision, timeout, role=None):
        service = get_ecs_task_name(self.reponame, env, role)
        cluster = get_ecs_cluster_name(self.ecs_cluster_basename, env)

        client = boto3.client('ecs')
        resp = client.update_service(
            service=service,
            cluster=cluster,
            taskDefinition=task_def_revision
        )

        if resp['service']['taskDefinition'] != task_def_revision:
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

    def backup_secrets(self, s3_bucket):
        backup_secrets(self.reponame, s3_bucket)

    def deploy(self, env, memory_reservation, no_service=False, cpu=None,
               memory_reservation_hard=False, ports=None, cmd=None, role=None,
               timeout=300):
        self.push_ecr_image()
        task_def = self.get_task_def(env,
                                     memory_reservation,
                                     cpu,
                                     memory_reservation_hard,
                                     ports,
                                     cmd,
                                     role)
        if env == 'test':
            from pprint import pprint
            pprint(task_def)
        else:
            task_def_revision = self.register_task_def(env, task_def, role)
            if not no_service:
                self.update_ecs_service(env, task_def_revision, timeout, role)
