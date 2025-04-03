#!/usr/bin/env python3
import git.exc
from tuda_workspace_scripts.workspace import get_workspace_root, PackageChoicesCompleter

import argcomplete
import argparse
import os
from ament_index_python.packages import get_package_share_directory

try:
    import git
except ImportError:
    print("GitPython is required! Install using 'apt install python3-git'")
    raise


def parseArguments() -> argparse.Namespace:

    parser = argparse.ArgumentParser(
        description="Creates a ROS 2 package from templates"
    )

    parser.add_argument(
        "--template",
        type=str,
        default=None,
        choices=["cpp_pkg", "msgs_pkg", "python_pkg", "ci"],
        help="Template",
    )
    parser.add_argument(
        "--destination",
        "-d",
        type=str,
        default=os.getcwd(),
        help="Destination directory (default: current working directory)",
    )
    parser.add_argument(
        "--defaults", action="store_true", help="Use defaults for all options"
    )

    parser.add_argument("--package-name", type=str, default=None, help="Package name")
    parser.add_argument("--description", type=str, default=None, help="Description")
    parser.add_argument("--maintainer", type=str, default=None, help="Maintainer")
    parser.add_argument(
        "--maintainer-email", type=str, default=None, help="Maintainer email"
    )
    parser.add_argument("--author", type=str, default=None, help="Author")
    parser.add_argument("--author-email", type=str, default=None, help="Author email")
    parser.add_argument(
        "--license",
        type=str,
        default=None,
        choices=[
            "Apache-2.0",
            "BSL-1.0",
            "BSD-2.0",
            "BSD-2-Clause",
            "BSD-3-Clause",
            "GPL-3.0-only",
            "LGPL-2.1-only",
            "LGPL-3.0-only",
            "MIT",
            "MIT-0",
        ],
        help="License",
    )
    parser.add_argument("--node-name", type=str, default=None, help="Node name")
    parser.add_argument(
        "--node-class-name", type=str, default=None, help="Class name of node"
    )
    parser.add_argument(
        "--is-component", action="store_true", default=None, help="Make it a component?"
    )
    parser.add_argument(
        "--is-lifecycle",
        action="store_true",
        default=None,
        help="Make it a lifecycle node?",
    )
    parser.add_argument(
        "--has-launch-file",
        action="store_true",
        default=None,
        help="Add a launch file?",
    )
    parser.add_argument(
        "--launch-file-type",
        type=str,
        choices=["xml", "py", "yml"],
        help="Type of launch file",
    )
    parser.add_argument(
        "--has-params", action="store_true", default=None, help="Add parameter loading"
    )
    parser.add_argument(
        "--has-subscriber", action="store_true", default=None, help="Add a subscriber?"
    )
    parser.add_argument(
        "--has-publisher", action="store_true", default=None, help="Add a publisher?"
    )
    parser.add_argument(
        "--has-service-server",
        action="store_true",
        default=None,
        help="Add a service server?",
    )
    parser.add_argument(
        "--has-action-server",
        action="store_true",
        default=None,
        help="Add an action server?",
    )
    parser.add_argument(
        "--has-timer", action="store_true", default=None, help="Add a timer callback?"
    )
    parser.add_argument(
        "--auto-shutdown",
        action="store_true",
        default=None,
        help="Automatically shutdown the node after launch (useful in CI/CD)?",
    )
    parser.add_argument(
        "--interface-types",
        type=str,
        default=None,
        choices=["Message", "Service", "Action"],
        help="Interfaces types",
    )
    parser.add_argument("--msg-name", type=str, default=None, help="Message name")
    parser.add_argument("--srv-name", type=str, default=None, help="Service name")
    parser.add_argument("--action-name", type=str, default=None, help="Action name")
    parser.add_argument(
        "--ci-type",
        type=str,
        choices=["github", "gitlab"],
        default=None,
        help="CI type",
    )
    parser.add_argument(
        "--add-pre-commit",
        action="store_true",
        default=None,
        help="Add pre-commit hook?",
    )

    argcomplete.autocomplete(parser)
    return parser.parse_args()


def add_git_config_info(answers):
    # add author and maintainer info from git config if not yet set
    git_config = git.GitConfigParser()
    git_config.read()
    if not answers.get("author") or not answers.get("maintainer"):
        answers["user_name_git"] = git_config.get_value("user", "name")
    if not answers.get("author_email") or not answers.get("maintainer_email"):
        answers["user_email_git"] = git_config.get_value("user", "email")


def add_git_provider(answers, repo_path="."):
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
        remotes = repo.remotes
        if "origin" in remotes:
            remote_url = remotes["origin"].url
        elif remotes:
            # fallback to first remote
            remote_url = list(remotes)[0].url
        else:
            # "No remotes found in repo"
            return

        if "github.com" in remote_url:
            answers["git_provider"] = "github"
        elif "gitlab" in remote_url:
            answers["git_provider"] = "gitlab"
    except Exception as e:
        # error while parsing git config
        # do not set git_provider
        pass


def add_ros_distro(answers):
    if os.environ.get("ROS_DISTRO"):
        answers["ros_distro"] = os.environ.get("ROS_DISTRO")


def create_from_template(template, destination, answers, defaults):
    try:
        import copier
    except ImportError:
        print(
            "Copier is required! Install using 'pip3 install copier --user --break-system-packages'"
        )
        raise

    # run copier
    try:
        copier.run_copy(
            template,
            destination,
            data=answers,
            defaults=defaults,
            unsafe=True,
            vcs_ref="HEAD",
        )

    except copier.CopierAnswersInterrupt:
        print("Aborted")
        return


def create(template_pkg_name: str, template_url: str):

    # pass specified arguments as data to copier
    args = parseArguments()
    workspace_src = os.path.join(get_workspace_root(), "src")

    # Adapt relative destination path
    if not os.path.isabs(args.destination):
        args.destination = os.path.join(workspace_src, args.destination)
    print(f"Destination: {args.destination}")

    answers = {k: v for k, v in vars(args).items() if v is not None}

    # add author and maintainer info from git config if not yet set
    add_git_config_info(answers)

    add_ros_distro(answers)

    add_git_provider(answers, args.destination)

    # get pkg template location if installed as ros pkg
    try:
        template_location = get_package_share_directory(template_pkg_name)
    except KeyError:
        print(
            f"Package '{template_pkg_name}' not found locally. Using remote template."
        )
        template_location = template_url
        
    create_from_template(template_location, args.destination, answers, args.defaults)


if __name__ == "__main__":
    template_pkg_name = "ros2_pkg_create"
    template_url = "https://github.com/tu-darmstadt-ros-pkg/ros2-pkg-create.git"
    create(template_pkg_name, template_url)
