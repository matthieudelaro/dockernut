from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import contextlib
import json
import logging
import re
import sys
from inspect import getdoc
from operator import attrgetter

from docker.errors import APIError
from requests.exceptions import ReadTimeout

from . import signals
from .. import __version__
from ..config import config
from ..config import ConfigurationError
from ..config import parse_environment
from ..config.serialize import serialize_config
from ..const import DEFAULT_TIMEOUT
from ..const import HTTP_TIMEOUT
from ..const import IS_WINDOWS_PLATFORM
from ..progress_stream import StreamOutputError
from ..project import NoSuchService
from ..service import BuildError
from ..service import ConvergenceStrategy
from ..service import ImageType
from ..service import NeedsBuildError
from .command import friendly_error_message
from .command import get_config_path_from_options
from .command import project_from_options
from .command import get_project
from .docopt_command import DocoptCommand
from .docopt_command import NoSuchCommand
from .errors import UserError
from .formatter import ConsoleWarningFormatter
from .formatter import Formatter
from .log_printer import LogPrinter
from .utils import get_version_info
from .utils import yesno

import os
from .nut import Nut
import urllib.request


if not IS_WINDOWS_PLATFORM:
    from dockerpty.pty import PseudoTerminal, RunOperation

log = logging.getLogger(__name__)
console_handler = logging.StreamHandler(sys.stderr)


def main():
    setup_logging()
    try:
        command = TopLevelCommand()
        command.sys_dispatch()
    except KeyboardInterrupt:
        log.error("Aborting.")
        sys.exit(1)
    except (UserError, NoSuchService, ConfigurationError) as e:
        log.error(e.msg)
        sys.exit(1)
    except NoSuchCommand as e:
        commands = "\n".join(parse_doc_section("commands:", getdoc(e.supercommand)))
        log.error("No such command: %s\n\n%s", e.command, commands)
        sys.exit(1)
    except APIError as e:
        log.error(e.explanation)
        sys.exit(1)
    except BuildError as e:
        log.error("Service '%s' failed to build: %s" % (e.service.name, e.reason))
        sys.exit(1)
    except StreamOutputError as e:
        log.error(e)
        sys.exit(1)
    except NeedsBuildError as e:
        log.error("Service '%s' needs to be built, but --no-build was passed." % e.service.name)
        sys.exit(1)
    except ReadTimeout as e:
        log.error(
            "An HTTP request took too long to complete. Retry with --verbose to obtain debug information.\n"
            "If you encounter this issue regularly because of slow network conditions, consider setting "
            "COMPOSE_HTTP_TIMEOUT to a higher value (current value: %s)." % HTTP_TIMEOUT
        )
        sys.exit(1)


def setup_logging():
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.DEBUG)

    # Disable requests logging
    logging.getLogger("requests").propagate = False


def setup_console_handler(handler, verbose):
    if handler.stream.isatty():
        format_class = ConsoleWarningFormatter
    else:
        format_class = logging.Formatter

    if verbose:
        handler.setFormatter(format_class('%(name)s.%(funcName)s: %(message)s'))
        handler.setLevel(logging.DEBUG)
    else:
        handler.setFormatter(format_class())
        handler.setLevel(logging.INFO)


# stolen from docopt master
def parse_doc_section(name, source):
    pattern = re.compile('^([^\n]*' + name + '[^\n]*\n?(?:[ \t].*?(?:\n|$))*)',
                         re.IGNORECASE | re.MULTILINE)
    return [s.strip() for s in pattern.findall(source)]


def loadConfig(baseDirectory, project):
    for envName in project.service_names:
        env = project.get_service(envName)

        path = env.getProjectConfig("env", "path")
        url = env.getProjectConfig("env", "url")
        git = env.getProjectConfig("env", "git")
        if path is not None:
            envConfigFullName = os.path.join(baseDirectory, path)
            envConfigDirectory = os.path.dirname(envConfigFullName)
            envConfigFileName = os.path.basename(envConfigFullName)
        elif url is not None:
            envConfigDirectory = os.path.join(baseDirectory, Nut.folder, envName)
            envConfigFullName = os.path.join(envConfigDirectory, Nut.defaultConfigFile)
            if not os.path.exists(envConfigDirectory):
                os.makedirs(envConfigDirectory)
                urllib.request.urlretrieve(url, envConfigFullName)
                log.info("Fetched file from url '%s' and created module '%s' from it.", url, envName)
            pass
        else:
            envConfigDirectory = os.path.join(baseDirectory, Nut.folder, envName)

        # load a custom yml script
        donut = get_project(envConfigDirectory, config_path=None, project_name=None, verbose=False)
        # donut = get_project(envConfigDirectory, config_path=["nut.yml"], project_name=None, verbose=False)
        # print()
        # print("donut", donut, "from path", envConfigDirectory)
        # print("the config loaded from the file: ", donut.get_service(donut.service_names[0]).projectConfig)  # here is the config

        env.setNutConfig(donut.get_service(donut.service_names[0]).projectConfig)
        # print("the config for the nut: ", env.nutConfig)  # here is the config
    pass


class TopLevelCommand(DocoptCommand):
    """Define and use a dev environment with Docker.

    Try "nut init" to create a boilerplate nut.yml file in the current directory.
    Modify it to fit your need. Then run "nut build" and "nut run" to build and
    run your app in a container.

    Usage:
      nut [-f=<arg>...] [options] [COMMAND] [ARGS...]
      nut -h|--help

    Options:
      -f, --file FILE           Specify an alternate compose file (default: nut.yml)
      -p, --project-name NAME   Specify an alternate project name (default: directory name)
      --verbose                 Show more output
      -v, --version             Print version and exit

    Commands:
      build              Build or rebuild app
      cmd                Run a command defined in configuration file
      exe                Run a command given as argument
      help               Get help on a command
      init               (yet to be implemented) Creates a boiler plate nut.yml file
      run                Run the app
      test               Run the tests
      version            Show the nut version information
    """
    base_dir = '.'

    def getEnv(self, project):
        return project.get_service(project.service_names[0])

    def docopt_options(self):
        options = super(TopLevelCommand, self).docopt_options()
        options['version'] = get_version_info('compose')
        return options

    def perform_command(self, options, handler, command_options):
        setup_console_handler(console_handler, options.get('--verbose'))

        if options['COMMAND'] in ('help', 'version'):
            # Skip looking up the compose file.
            handler(None, command_options)
            return

        if options['COMMAND'] == 'config':
            handler(options, command_options)
            return

        project = project_from_options(self.base_dir, options)

        loadConfig(self.base_dir, project)
        # # load a custom yml script
        # donut = get_project(os.path.join(self.base_dir, ".nut", "go"), config_path=["nut.yml"], project_name=None, verbose=True)
        # print()
        # print("donut", donut)
        # print("the config loaded from the file: ", self.getEnv(donut).projectConfig)  # here is the config

        with friendly_error_message():
            handler(project, command_options)

    def build(self, project, options):
        """
        Build or rebuild app.

        Usage: build [ARGS...]
        """
        # project.build(
        #     service_names=options['SERVICE'],
        #     no_cache=bool(options.get('--no-cache', False)),
        #     pull=bool(options.get('--pull', False)),
        #     force_rm=bool(options.get('--force-rm', False)))
        self.getEnv(project).build(options["ARGS"])

    def cmd(self, project, options):
        """
        Run command defined in the project configuration.

        Usage: cmd COMMAND [ARGS...]
        """
        #  cmd [command] [ARGS...]
        # print("hello")
        # print("environments:", project.service_names)
        # print("environment:", project.get_service(project.service_names[0]).name)
        # print(options)
        # project.get_service(project.service_names[0]).run(options["ARGS"])
        self.getEnv(project).cmd(options["COMMAND"], options["ARGS"])
        # project.get_service(project.service_names[0]).run(["echo", "hello"])
        # project.get_service(project.service_names[0]).pull()
        # print(project.get_service(project.service_names[0]).image)

    def exe(self, project, options):
        """
        Run command given as argument.

        Usage: exe [ARGS...]
        """
        self.getEnv(project).exe(options["ARGS"])

    def init(self, project, options):
        """
        Creates a boiler plate nut.yml file.

        Usage: init
        """
        # todo: solve error "ERROR: Top level object in './nut.yml' needs to be an object not '<class 'NoneType'>'."
        # explanation: nut first looks for a nut.yml file, which of course does not exist yet.
        boilerplate = """go:
                          env:
                            path: exampleOfLocalNutFile/go/nut.yml
                          commands:
                            helloworld:
                              - echo "Hello World!"""
        filename = os.path.join(self.base_dir, Nut.defaultConfigFile)
        f = open(filename, 'w')
        f.write(boilerplate)
        log.info("The boilerplate nut.yml file has been created:")
        call(["cat", filename])  # todo: not cross plateform


    def run(self, project, options):
        """
        Runs the service.

        Usage: run [ARGS...]
        """
        self.getEnv(project).run(options["ARGS"])

    def test(self, project, options):
        """
        Runs the tests.

        Usage: test [ARGS...]
        """
        self.getEnv(project).test(options["ARGS"])

    # def config(self, config_options, options):
    #     """
    #     Validate and view the compose file.

    #     Usage: config [options]

    #     Options:
    #         -q, --quiet     Only validate the configuration, don't print
    #                         anything.
    #         --services      Print the service names, one per line.

    #     """
    #     config_path = get_config_path_from_options(config_options)
    #     compose_config = config.load(config.find(self.base_dir, config_path))

    #     if options['--quiet']:
    #         return

    #     if options['--services']:
    #         print('\n'.join(service['name'] for service in compose_config.services))
    #         return

    #     print(serialize_config(compose_config))

    # def create(self, project, options):
    #     """
    #     Creates containers for a service.

    #     Usage: create [options] [SERVICE...]

    #     Options:
    #         --force-recreate       Recreate containers even if their configuration and
    #                                image haven't changed. Incompatible with --no-recreate.
    #         --no-recreate          If containers already exist, don't recreate them.
    #                                Incompatible with --force-recreate.
    #         --no-build             Don't build an image, even if it's missing
    #     """
    #     service_names = options['SERVICE']

    #     project.create(
    #         service_names=service_names,
    #         strategy=convergence_strategy_from_opts(options),
    #         do_build=not options['--no-build']
    #     )

    # def down(self, project, options):
    #     """
    #     Stop containers and remove containers, networks, volumes, and images
    #     created by `up`. Only containers and networks are removed by default.

    #     Usage: down [options]

    #     Options:
    #         --rmi type      Remove images, type may be one of: 'all' to remove
    #                         all images, or 'local' to remove only images that
    #                         don't have an custom name set by the `image` field
    #         -v, --volumes   Remove data volumes
    #     """
    #     image_type = image_type_from_opt('--rmi', options['--rmi'])
    #     project.down(image_type, options['--volumes'])

    # def events(self, project, options):
    #     """
    #     Receive real time events from containers.

    #     Usage: events [options] [SERVICE...]

    #     Options:
    #         --json      Output events as a stream of json objects
    #     """
    #     def format_event(event):
    #         attributes = ["%s=%s" % item for item in event['attributes'].items()]
    #         return ("{time} {type} {action} {id} ({attrs})").format(
    #             attrs=", ".join(sorted(attributes)),
    #             **event)

    #     def json_format_event(event):
    #         event['time'] = event['time'].isoformat()
    #         return json.dumps(event)

    #     for event in project.events():
    #         formatter = json_format_event if options['--json'] else format_event
    #         print(formatter(event))
    #         sys.stdout.flush()

    def help(self, project, options):
        """
        Get help on a command.

        Usage: help COMMAND
        """
        handler = self.get_handler(options['COMMAND'])
        raise SystemExit(getdoc(handler))

    # def kill(self, project, options):
    #     """
    #     Force stop service containers.

    #     Usage: kill [options] [SERVICE...]

    #     Options:
    #         -s SIGNAL         SIGNAL to send to the container.
    #                           Default signal is SIGKILL.
    #     """
    #     signal = options.get('-s', 'SIGKILL')

    #     project.kill(service_names=options['SERVICE'], signal=signal)

    # def logs(self, project, options):
    #     """
    #     View output from containers.

    #     Usage: logs [options] [SERVICE...]

    #     Options:
    #         --no-color  Produce monochrome output.
    #     """
    #     containers = project.containers(service_names=options['SERVICE'], stopped=True)

    #     monochrome = options['--no-color']
    #     print("Attaching to", list_containers(containers))
    #     LogPrinter(containers, monochrome=monochrome).run()

    # def pause(self, project, options):
    #     """
    #     Pause services.

    #     Usage: pause [SERVICE...]
    #     """
    #     containers = project.pause(service_names=options['SERVICE'])
    #     exit_if(not containers, 'No containers to pause', 1)

    # def port(self, project, options):
    #     """
    #     Print the public port for a port binding.

    #     Usage: port [options] SERVICE PRIVATE_PORT

    #     Options:
    #         --protocol=proto  tcp or udp [default: tcp]
    #         --index=index     index of the container if there are multiple
    #                           instances of a service [default: 1]
    #     """
    #     index = int(options.get('--index'))
    #     service = project.get_service(options['SERVICE'])
    #     try:
    #         container = service.get_container(number=index)
    #     except ValueError as e:
    #         raise UserError(str(e))
    #     print(container.get_local_port(
    #         options['PRIVATE_PORT'],
    #         protocol=options.get('--protocol') or 'tcp') or '')

    # def ps(self, project, options):
    #     """
    #     List containers.

    #     Usage: ps [options] [SERVICE...]

    #     Options:
    #         -q    Only display IDs
    #     """
    #     containers = sorted(
    #         project.containers(service_names=options['SERVICE'], stopped=True) +
    #         project.containers(service_names=options['SERVICE'], one_off=True),
    #         key=attrgetter('name'))

    #     if options['-q']:
    #         for container in containers:
    #             print(container.id)
    #     else:
    #         headers = [
    #             'Name',
    #             'Command',
    #             'State',
    #             'Ports',
    #         ]
    #         rows = []
    #         for container in containers:
    #             command = container.human_readable_command
    #             if len(command) > 30:
    #                 command = '%s ...' % command[:26]
    #             rows.append([
    #                 container.name,
    #                 command,
    #                 container.human_readable_state,
    #                 container.human_readable_ports,
    #             ])
    #         print(Formatter().table(headers, rows))

    # def pull(self, project, options):
    #     """
    #     Pulls images for services.

    #     Usage: pull [options] [SERVICE...]

    #     Options:
    #         --ignore-pull-failures  Pull what it can and ignores images with pull failures.
    #     """
    #     project.pull(
    #         service_names=options['SERVICE'],
    #         ignore_pull_failures=options.get('--ignore-pull-failures')
    #     )

    # def rm(self, project, options):
    #     """
    #     Remove stopped service containers.

    #     By default, volumes attached to containers will not be removed. You can see all
    #     volumes with `docker volume ls`.

    #     Any data which is not in a volume will be lost.

    #     Usage: rm [options] [SERVICE...]

    #     Options:
    #         -f, --force   Don't ask to confirm removal
    #         -v            Remove volumes associated with containers
    #     """
    #     all_containers = project.containers(service_names=options['SERVICE'], stopped=True)
    #     stopped_containers = [c for c in all_containers if not c.is_running]

    #     if len(stopped_containers) > 0:
    #         print("Going to remove", list_containers(stopped_containers))
    #         if options.get('--force') \
    #                 or yesno("Are you sure? [yN] ", default=False):
    #             project.remove_stopped(
    #                 service_names=options['SERVICE'],
    #                 v=options.get('-v', False)
    #             )
    #     else:
    #         print("No stopped containers")

    # def run(self, project, options):
    #     """
    #     Run a one-off command on a service.

    #     For example:

    #         $ docker-compose run web python manage.py shell

    #     By default, linked services will be started, unless they are already
    #     running. If you do not want to start linked services, use
    #     `docker-compose run --no-deps SERVICE COMMAND [ARGS...]`.

    #     Usage: run [options] [-p PORT...] [-e KEY=VAL...] SERVICE [COMMAND] [ARGS...]

    #     Options:
    #         -d                    Detached mode: Run container in the background, print
    #                               new container name.
    #         --name NAME           Assign a name to the container
    #         --entrypoint CMD      Override the entrypoint of the image.
    #         -e KEY=VAL            Set an environment variable (can be used multiple times)
    #         -u, --user=""         Run as specified username or uid
    #         --no-deps             Don't start linked services.
    #         --rm                  Remove container after run. Ignored in detached mode.
    #         -p, --publish=[]      Publish a container's port(s) to the host
    #         --service-ports       Run command with the service's ports enabled and mapped
    #                               to the host.
    #         -T                    Disable pseudo-tty allocation. By default `docker-compose run`
    #                               allocates a TTY.
    #     """
    #     service = project.get_service(options['SERVICE'])
    #     detach = options['-d']

    #     if IS_WINDOWS_PLATFORM and not detach:
    #         raise UserError(
    #             "Interactive mode is not yet supported on Windows.\n"
    #             "Please pass the -d flag when using `docker-compose run`."
    #         )

    #     if options['COMMAND']:
    #         command = [options['COMMAND']] + options['ARGS']
    #     else:
    #         command = service.options.get('command')

    #     container_options = {
    #         'command': command,
    #         'tty': not (detach or options['-T'] or not sys.stdin.isatty()),
    #         'stdin_open': not detach,
    #         'detach': detach,
    #     }

    #     if options['-e']:
    #         container_options['environment'] = parse_environment(options['-e'])

    #     if options['--entrypoint']:
    #         container_options['entrypoint'] = options.get('--entrypoint')

    #     if options['--rm']:
    #         container_options['restart'] = None

    #     if options['--user']:
    #         container_options['user'] = options.get('--user')

    #     if not options['--service-ports']:
    #         container_options['ports'] = []

    #     if options['--publish']:
    #         container_options['ports'] = options.get('--publish')

    #     if options['--publish'] and options['--service-ports']:
    #         raise UserError(
    #             'Service port mapping and manual port mapping '
    #             'can not be used togather'
    #         )

    #     if options['--name']:
    #         container_options['name'] = options['--name']

    #     run_one_off_container(container_options, project, service, options)

    # def scale(self, project, options):
    #     """
    #     Set number of containers to run for a service.

    #     Numbers are specified in the form `service=num` as arguments.
    #     For example:

    #         $ docker-compose scale web=2 worker=3

    #     Usage: scale [options] [SERVICE=NUM...]

    #     Options:
    #       -t, --timeout TIMEOUT      Specify a shutdown timeout in seconds.
    #                                  (default: 10)
    #     """
    #     timeout = int(options.get('--timeout') or DEFAULT_TIMEOUT)

    #     for s in options['SERVICE=NUM']:
    #         if '=' not in s:
    #             raise UserError('Arguments to scale should be in the form service=num')
    #         service_name, num = s.split('=', 1)
    #         try:
    #             num = int(num)
    #         except ValueError:
    #             raise UserError('Number of containers for service "%s" is not a '
    #                             'number' % service_name)
    #         project.get_service(service_name).scale(num, timeout=timeout)

    # def start(self, project, options):
    #     """
    #     Start existing containers.

    #     Usage: start [SERVICE...]
    #     """
    #     containers = project.start(service_names=options['SERVICE'])
    #     exit_if(not containers, 'No containers to start', 1)

    # def stop(self, project, options):
        """
        Stop running containers without removing them.

        They can be started again with `docker-compose start`.

        Usage: stop [options] [SERVICE...]

        Options:
          -t, --timeout TIMEOUT      Specify a shutdown timeout in seconds.
                                     (default: 10)
        """
        timeout = int(options.get('--timeout') or DEFAULT_TIMEOUT)
        project.stop(service_names=options['SERVICE'], timeout=timeout)

    # def restart(self, project, options):
    #     """
    #     Restart running containers.

    #     Usage: restart [options] [SERVICE...]

    #     Options:
    #       -t, --timeout TIMEOUT      Specify a shutdown timeout in seconds.
    #                                  (default: 10)
    #     """
    #     timeout = int(options.get('--timeout') or DEFAULT_TIMEOUT)
    #     containers = project.restart(service_names=options['SERVICE'], timeout=timeout)
    #     exit_if(not containers, 'No containers to restart', 1)

    # def unpause(self, project, options):
    #     """
    #     Unpause services.

    #     Usage: unpause [SERVICE...]
    #     """
    #     containers = project.unpause(service_names=options['SERVICE'])
    #     exit_if(not containers, 'No containers to unpause', 1)

    # def up(self, project, options):
    #     """
    #     Builds, (re)creates, starts, and attaches to containers for a service.

    #     Unless they are already running, this command also starts any linked services.

    #     The `docker-compose up` command aggregates the output of each container. When
    #     the command exits, all containers are stopped. Running `docker-compose up -d`
    #     starts the containers in the background and leaves them running.

    #     If there are existing containers for a service, and the service's configuration
    #     or image was changed after the container's creation, `docker-compose up` picks
    #     up the changes by stopping and recreating the containers (preserving mounted
    #     volumes). To prevent Compose from picking up changes, use the `--no-recreate`
    #     flag.

    #     If you want to force Compose to stop and recreate all containers, use the
    #     `--force-recreate` flag.

    #     Usage: up [options] [SERVICE...]

    #     Options:
    #         -d                         Detached mode: Run containers in the background,
    #                                    print new container names.
    #                                    Incompatible with --abort-on-container-exit.
    #         --no-color                 Produce monochrome output.
    #         --no-deps                  Don't start linked services.
    #         --force-recreate           Recreate containers even if their configuration
    #                                    and image haven't changed.
    #                                    Incompatible with --no-recreate.
    #         --no-recreate              If containers already exist, don't recreate them.
    #                                    Incompatible with --force-recreate.
    #         --no-build                 Don't build an image, even if it's missing
    #         --abort-on-container-exit  Stops all containers if any container was stopped.
    #                                    Incompatible with -d.
    #         -t, --timeout TIMEOUT      Use this timeout in seconds for container shutdown
    #                                    when attached or when containers are already
    #                                    running. (default: 10)
    #     """
    #     monochrome = options['--no-color']
    #     start_deps = not options['--no-deps']
    #     cascade_stop = options['--abort-on-container-exit']
    #     service_names = options['SERVICE']
    #     timeout = int(options.get('--timeout') or DEFAULT_TIMEOUT)
    #     detached = options.get('-d')

    #     if detached and cascade_stop:
    #         raise UserError("--abort-on-container-exit and -d cannot be combined.")

    #     with up_shutdown_context(project, service_names, timeout, detached):
    #         to_attach = project.up(
    #             service_names=service_names,
    #             start_deps=start_deps,
    #             strategy=convergence_strategy_from_opts(options),
    #             do_build=not options['--no-build'],
    #             timeout=timeout,
    #             detached=detached)

    #         if detached:
    #             return
    #         log_printer = build_log_printer(to_attach, service_names, monochrome, cascade_stop)
    #         print("Attaching to", list_containers(log_printer.containers))
    #         log_printer.run()

    def version(self, project, options):
        """
        Show version informations

        Usage: version [--short]

        Options:
            --short     Shows only Compose's version number.
        """
        if options['--short']:
            print(__version__)
        else:
            print(get_version_info('full'))



def convergence_strategy_from_opts(options):
    no_recreate = options['--no-recreate']
    force_recreate = options['--force-recreate']
    if force_recreate and no_recreate:
        raise UserError("--force-recreate and --no-recreate cannot be combined.")

    if force_recreate:
        return ConvergenceStrategy.always

    if no_recreate:
        return ConvergenceStrategy.never

    return ConvergenceStrategy.changed


def image_type_from_opt(flag, value):
    if not value:
        return ImageType.none
    try:
        return ImageType[value]
    except KeyError:
        raise UserError("%s flag must be one of: all, local" % flag)


def run_one_off_container(container_options, project, service, options):
    if not options['--no-deps']:
        deps = service.get_linked_service_names()
        if deps:
            project.up(
                service_names=deps,
                start_deps=True,
                strategy=ConvergenceStrategy.never)

    project.initialize()

    container = service.create_container(
        quiet=True,
        one_off=True,
        **container_options)

    if options['-d']:
        service.start_container(container)
        print(container.name)
        return

    def remove_container(force=False):
        if options['--rm']:
            project.client.remove_container(container.id, force=True)

    signals.set_signal_handler_to_shutdown()
    try:
        try:
            operation = RunOperation(
                project.client,
                container.id,
                interactive=not options['-T'],
                logs=False,
            )
            pty = PseudoTerminal(project.client, operation)
            sockets = pty.sockets()
            service.start_container(container)
            pty.start(sockets)
            exit_code = container.wait()
        except signals.ShutdownException:
            project.client.stop(container.id)
            exit_code = 1
    except signals.ShutdownException:
        project.client.kill(container.id)
        remove_container(force=True)
        sys.exit(2)

    remove_container()
    sys.exit(exit_code)


def build_log_printer(containers, service_names, monochrome, cascade_stop):
    if service_names:
        containers = [
            container
            for container in containers if container.service in service_names
        ]
    return LogPrinter(containers, monochrome=monochrome, cascade_stop=cascade_stop)


@contextlib.contextmanager
def up_shutdown_context(project, service_names, timeout, detached):
    if detached:
        yield
        return

    signals.set_signal_handler_to_shutdown()
    try:
        try:
            yield
        except signals.ShutdownException:
            print("Gracefully stopping... (press Ctrl+C again to force)")
            project.stop(service_names=service_names, timeout=timeout)
    except signals.ShutdownException:
        project.kill(service_names=service_names)
        sys.exit(2)


def list_containers(containers):
    return ", ".join(c.name for c in containers)


def exit_if(condition, message, exit_code):
    if condition:
        log.error(message)
        raise SystemExit(exit_code)
