#!/usr/bin/python
# this script now needs python 3.6+ to run thanks to secrets (read: if you just installed python, all is fine)

# all the stuff we need
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys

CYAN = "\033[1;36m"
YELLOW = "\033[1;33m"
# checks for windows
IS_WINDOWS = os.name == "nt"
USE_COLOR = not IS_WINDOWS
SUBPROCESS_KWARGS = dict(shell=True) if IS_WINDOWS else dict()
IMPORT_COMMAND = "importtournament"
PS_SCALE = "ps:scale"

def echo(message, color=None):
    if color and USE_COLOR:
        message = color + message + "\033[0m"
    print(message)

def redact(command):
    return ["DJANGO_SECRET_KEY=***" if arg.startswith("DJANGO_SECRET_KEY=") else arg for arg in command]

class Runner:
    def __init__(self, dry_run):
        self.dry_run = dry_run
    def heroku(self, *args, app_name, capture=False, tolerate_failure=False, auth=False):
        command = ["heroku"] + list(args) + ["--app", app_name]
        return self.run(command, capture=capture, tolerate_failure=tolerate_failure, auth=auth)
    def run(self, command, capture=False, tolerate_failure=False, auth=False):
        echo("$ " + " ".join(redact(command)), CYAN)
        if self.dry_run:
            return ""
        try:
            if capture:
                output = subprocess.check_output(command, **SUBPROCESS_KWARGS)
                text = output.decode()
                sys.stdout.write(text)
                sys.stdout.flush()
                return text
            subprocess.check_call(command, **SUBPROCESS_KWARGS)
            return ""
        except subprocess.CalledProcessError as exc:
            if tolerate_failure:
                return None
            if auth:
                echo("Command %s failed, exit code %d. Authenticate via 'heroku login' first." % (" ".join(command), exc.returncode), YELLOW)
                sys.exit(exc.returncode or 1)
            echo("Command failed, exit code %d: %s" % (exc.returncode, " ".join(redact(command))), YELLOW)
            echo("The Heroku app might be partially configured; please check the dashboard before retrying.", YELLOW)
            sys.exit(exc.returncode or 1)

# arguments. these worked, so don't change what isn't broken
def build_parser():
    parser = argparse.ArgumentParser(description="Deploy Tabbycat to a new Heroku app.")

    parser.add_argument(
        "urlname", type=str,
        help="Name of the Heroku app. The app will be at urlname.herokuapp.com. Use '-' to use a Heroku-generated default.")

    parser.add_argument(
        "--no-open", action="store_false", default=True, dest="open",
        help="Don't open the Heroku website in your browser at the end")

    parser.add_argument(
        "--git-remote", type=str, default=None,
        help="Name of Git remote to use. Use '-' to use the urlname. If omitted, reverts to default Heroku behaviour.")

    parser.add_argument(
        "--git-branch", type=str, default=None,
        help="Git branch to push (defaults to current branch)")

    parser.add_argument(
        "--pg-plan", "--postgresql-plan", type=str, default="essential-0",
        help="Heroku Postgres plan (default essential-0)")

    parser.add_argument(
        "--web-dynos", type=str, default="1",
        help="Web dyno specification, passed to heroku %s web=[], e.g. 1:eco, 1:basic, 2:Standard-1X" % PS_SCALE)

    parser.add_argument(
        "--import-tournament", type=str, metavar="IMPORT_DIR",
        help="Also run the %s command, importing from IMPORT_DIR" % IMPORT_COMMAND)

    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Print commands, don't run them.")

    config_group = parser.add_argument_group("heroku configuration settings")
    config_group.add_argument("--fast-cache-timeout", type=int, default=None, metavar="TIMEOUT",
                              help="Set the faster public page cache timeout to TIMEOUT")
    config_group.add_argument("--slow-cache-timeout", type=int, default=None, metavar="TIMEOUT",
                              help="Set the slower public page cache timeout to TIMEOUT")
    config_group.add_argument("--tab-cache-timeout", type=int, default=None, metavar="TIMEOUT",
                              help="Set the tab page cache timeout to TIMEOUT")
    config_group.add_argument("--enable-debug", action="store_true", default=False,
                              help="Enable Django debug pages")
    config_group.add_argument("--time-zone", type=str, default="Australia/Melbourne",
                              help="Time zone name from the IANA tz database")

    import_tournament_group = parser.add_argument_group(
        "import tournament options",
        "Passed to the %s command. Ignored unless " % IMPORT_COMMAND +
        "--import-tournament is used. Provided for convenience; to use other " +
        "%s options, run the %s command separately instead." % (IMPORT_COMMAND, IMPORT_COMMAND))
    import_tournament_group.add_argument(
        '-s', '--slug', type=str, action='store', default=None, dest="tournament_slug",
        help='Override tournament slug. (Default: use name of directory.)')
    import_tournament_group.add_argument(
        '--name', type=str, action='store', default=None, dest="tournament_name",
        help='Override tournament name. (Default: use name of directory.)')
    import_tournament_group.add_argument(
        '--short-name', type=str, action='store', default=None, dest="tournament_short_name",
        help='Override tournament short name. (Default: use name of directory.)')

    return parser

# get the app
def parse_app(output, fallback_name):
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
    try:
        app = json.loads(clean)
    except (ValueError, TypeError):
        app = None
    if isinstance(app, dict):
        name = app.get("name") or fallback_name
        web_url = app.get("web_url")
        if name:
            if web_url and not web_url.endswith("/"):
                web_url += "/"
            return name, web_url
    match = re.search(r"https://git\.heroku\.com/([\w_-]+)\.git", clean)
    if match:
        return match.group(1), None
    return fallback_name, None

# push .git, and if we can't find the git commit/branch to push make the user specify (hopefully never)
def get_git(runner, args):
    if args.git_branch:
        return "master" if args.git_branch == "master" else args.git_branch + ":master"
    branch = runner.run(["git", "symbolic-ref", "--short", "--quiet", "HEAD"], capture=True, tolerate_failure=True)
    if runner.dry_run:
        return "<branch>:master"
    if branch is not None:
        branch = branch.strip()
        return "master" if branch == "master" else branch + ":master"
    echo("Couldn't find a branch name. Fishing for commits instead...", YELLOW)
    commit = runner.run(["git", "rev-parse", "--short", "--quiet", "HEAD"], capture=True, tolerate_failure=True)
    if commit is not None:
        return commit.strip() + ":refs/heads/master"
    echo("Couldn't get the current git commit or branch. Use --git-branch to specify a git branch to push.", YELLOW)
    sys.exit(1)

def deploy(args):
    if args.dry_run:
        echo("dry_run doesn't actually find the app name or branch. those are resolved during actual runtime.")
    runner = Runner(args.dry_run)
    secret_key = secrets.token_urlsafe(50)
    runner.run(["heroku", "auth:whoami"], auth=True)
    # required...
    addons = ["papertrail", "heroku-postgresql:%s" % args.pg_plan, "rediscloud:30", "heroku-redis:mini"]
    # heroku-26 is heroku's current default stack
    # when it goes EOL, change the last digit and you're done
    create = ["heroku", "apps:create", "--json", "--stack", "heroku-26", "--addons", ",".join(addons)]
    if args.urlname != "-":
        create.append(args.urlname)
    output = runner.run(create, capture=True)
    if args.dry_run:
        app_name = args.urlname if args.urlname != "-" else "<app-name>"
        web_url = None
    else:
        app_name, web_url = parse_app(output, args.urlname if args.urlname != "-" else None)
        if not app_name:
            echo("Couldn't get the Heroku app name.", YELLOW)
            print("Heroku has this to say:")
            print(repr(output))
            return 1

    # we give the django secret to the config and keep it hidden from echo'd outputs
    config = ["config:set", "DISABLE_COLLECTSTATIC=1", "ON_HEROKU=1", "USING_NGINX=1",
              "DJANGO_SECRET_KEY=%s" % secret_key, "DEBUG=1" if args.enable_debug else "DEBUG=0"]
    if args.fast_cache_timeout is not None:
        config.append("PUBLIC_FAST_CACHE_TIMEOUT=%d" % args.fast_cache_timeout)
    if args.slow_cache_timeout is not None:
        config.append("PUBLIC_SLOW_CACHE_TIMEOUT=%d" % args.slow_cache_timeout)
    if args.tab_cache_timeout is not None:
        config.append("TAB_PAGES_CACHE_TIMEOUT=%d" % args.tab_cache_timeout)
    config.append("TIME_ZONE=%s" % args.time_zone)
    runner.heroku(*config, app_name=app_name)

    runner.heroku("buildpacks:set", "https://github.com/heroku/heroku-buildpack-nginx.git", app_name=app_name)
    runner.heroku("buildpacks:add", "heroku/nodejs", app_name=app_name)
    runner.heroku("buildpacks:add", "heroku/python", app_name=app_name)

    if args.git_remote:
        remote_name = args.git_remote if args.git_remote != "-" else app_name
        runner.heroku("git:remote", "--remote", remote_name, app_name=app_name)
    else:
        remote_name = "https://git.heroku.com/%s.git" % app_name

    echo("Waiting for Postgres and Redis to provision...", YELLOW)
    runner.heroku("pg:wait", app_name=app_name)
    runner.heroku("redis:wait", app_name=app_name)
    print("Done. Moving on...")
    push_spec = get_git(runner, args)
    runner.run(["git", "push", remote_name, push_spec])
    runner.heroku(PS_SCALE, "worker=1", "web=%s" % args.web_dynos, app_name=app_name)

    if args.import_tournament:
        command = ["run", "python", "tabbycat/manage.py", IMPORT_COMMAND, args.import_tournament]
        if args.tournament_slug:
            command += ["--slug", args.tournament_slug]
        if args.tournament_name:
            command += ["--name", args.tournament_name]
        if args.tournament_short_name:
            command += ["--short-name", args.tournament_short_name]
        runner.heroku(*command, app_name=app_name)

    if args.open:
        if runner.heroku("open", app_name=app_name, tolerate_failure=True) is None:
            echo("Tiny problem: couldn't open the URL.", YELLOW)
            echo("Here's the URL so you can visit it yourself.", YELLOW)
            # if we can't parse the JSON and there ends up being a random suffix this will fall through and require one to manually check the dashboard
            echo(web_url if web_url else "https://%s.herokuapp.com/" % app_name, YELLOW)

    return 0

# friendly reminder to install heroku CLI pretty please with a cherry on top
def main(argv=None):
    args = build_parser().parse_args(argv)
    if shutil.which("heroku") is None:
        echo("Couldn't find the Heroku CLI, which is needed to deploy Tabbycat through this script.", YELLOW)
        print("Head https://devcenter.heroku.com/articles/heroku-cli, or search the")
        print("internet for \"Heroku CLI\".")
        return 1
    return deploy(args)

if __name__ == "__main__":
    sys.exit(main())