#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
# This script checks all repositories located in the workspace folder and for each package
# resolves the binary using rosdep, the binary info is checked for the homepage. If the
# homepage follows the scheme ${GIT_REPO}#${BRANCH}, it is checked whether the repo is on the same
# branch and does not diverge from the remote in any way. If this is true for all packages in
# the repository, the repo can be replaced by the binaries.
from __future__ import print_function
from builtins import input
try:
  import apt
except ImportError:
  print("python-apt is required! Install using 'sudo apt install python-apt'")
  exit(1)
try:
  import git
except ImportError:
  print("GitPython is required! Install using 'pip install --user gitpython'")
  exit(1)
import argparse
try:
  import argcomplete
  __argcomplete = True
except ImportError:
  __argcomplete = False
import os
import re
import rosdep2
import rospkg
from shutil import rmtree
import subprocess
import sys

class Style:
  Error='\033[0;31m'
  Warning='\033[0;33m'
  Info='\033[0;34m'
  Success='\033[0;32m'
  Reset='\033[0;39m'

def printWithStyle(style, msg):
  print(style + msg + Style.Reset)

class RepoState:
  def __init__(self):
    self.clean = True
    self.pkgs = []
    self.binaries = {}

def multiselect(options, selection_text="Select", confirmOnEmpty=False):
  selected = [False]*len(options)
  selection = "-*"
  range_regex = re.compile("([0-9]+)-([0-9]+)")
  number_regex = re.compile("([0-9]+)")
  while True:
    cmds = selection.split(",")
    for cmd in cmds:
      cmd = cmd.strip()
      if len(cmd) == 0:
        continue
      val = True
      if cmd[0] == '-':
        cmd = cmd[1:]
        val = False
      if cmd == '*':
        for i in range(0, len(selected)):
          selected[i] = val
        continue
      match = range_regex.match(cmd)
      if match is not None:
        for i in range(int(match.group(1))-1, int(match.group(2))):
          selected[i] = val
        continue
      match = number_regex.match(cmd)
      if match is None:
        printWithStyle(Style.Error, "Invalid command: {}".format(cmd if val else '-'+cmd))
        continue
      selected[int(match.group(1))-1] = val

    for i, item in enumerate(options):
      if isinstance(item, str):
        print("{} {}: {}".format('*' if selected[i] else ' ', i+1, item))
      else:
        header, items = item
        print("{} {}: {}".format('*' if selected[i] else ' ', i+1, header))
        for item in items:
          print("  - {}".format(item))
    printWithStyle(Style.Info, "{} selected.".format(sum(selected)))
    selection = input("{}{}{}>> ".format(Style.Info, selection_text, Style.Reset))
    if selection == "":
      if sum(selected) > 0 or confirmOnEmpty == False:
        break
      while True:
        selection = input("{} (Y/n)? ".format("Are you sure you don't want to select anything" if not isinstance(confirmOnEmpty, str) else confirmOnEmpty))
        if re.match('[yY](?:[eE][sS])?', selection) is not None or re.match('[nN][oO]?', selection) is not None:
          break
      if re.match('[yY](?:[eE][sS])?', selection) is not None:
        break
      selection = ""
  return selected

if __name__ == "__main__":
  ws_src_path = os.environ.get("ROS_WORKSPACE")
  if ws_src_path is None:
    print("No workspace found! Did you source the setup.bash?")
    exit(1)
  ws_root = os.path.split(ws_src_path)[0]
  roswss_prefix = os.environ.get("ROSWSS_PREFIX", "roswss")

  parser = argparse.ArgumentParser(usage="{} desourcify".format(roswss_prefix),
                                   description="Searches for repositories in your workspace that could be deleted and replaced by binaries.")
  package_arg = parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Verbose output, e.g., why a repo was not replaced.")
  parser.add_argument("--no-debs", action="store_true", default=False, help="Don't check for and don't install replacement debian packages.")
  if __argcomplete:
    argcomplete.autocomplete(parser)
  args = parser.parse_args()
  
  print("Collecting packages", end='')
  sys.stdout.flush()
  
  rospack = rospkg.RosPack([ws_src_path])
  rosdep_installer_context = rosdep2.create_default_installer_context()
  rosdep_lookup = rosdep2.RosdepLookup.create_from_rospkg()
  rosdep_os_name, rosdep_os_version = rosdep_installer_context.get_os_name_and_version()
  rosdep_view = rosdep_lookup.get_rosdep_view(rosdep2.rospkg_loader.DEFAULT_VIEW_KEY)
  rosdep_apt_installer = rosdep_installer_context.get_installer("apt")
  git_commit_id_regex = re.compile(".*-[0-9]+UTC-([a-zA-Z0-9]+)")
  git_info_regex = re.compile("(.*\.git)#(.*)")

  apt_cache = apt.Cache()
  # Stores git repos as map: path -> clean
  git_repos = {}
  pkgs = rospack.list()
  for i, pkg in enumerate(pkgs):
    print("\033[KProcessed {} out of {} packages.".format(i+1, len(pkgs)), end='\r')
    sys.stdout.flush()
    full_pkg_path = rospack.get_path(pkg)
    try:
      repo = git.Repo(full_pkg_path, search_parent_directories=True)
    except git.exc.InvalidGitRepositoryError:
      # Not in a git repo
      if args.verbose: print("\033[K{} not removable because it is not in a git repo.".format(pkg))
      continue
    repo_ws_path = os.path.relpath(str(repo.working_dir), ws_root)
    if not repo_ws_path in git_repos:
      git_repos[repo_ws_path] = RepoState()
    repo_state = git_repos[repo_ws_path]
    repo_state.pkgs.append(pkg)
    if not repo_state.clean:
      # This repo is dirty, don't have to check
      continue
    repo_state.clean = False

    if repo.head.is_detached or repo.is_dirty() or len(repo.untracked_files) > 0:
      if args.verbose: print("\033[K{} not removable because it is dirty or contains untracked files.".format(repo_ws_path))
      continue
    
    # Make sure there are no stashed changes
    if any(repo.git.stash('list')):
      if args.verbose: print("\033[K{} not removable because it has stashed changes.".format(repo_ws_path))
      continue

    # Make sure there are no unpushed commits
    valid=True
    for branch in repo.branches:
      try:
        if any(True for _ in repo.iter_commits('{0}@{{u}}..{0}'.format(branch.name))):
          valid=False
          printWithStyle(Style.Warning, "\033[K{} has unpushed commits on branch {}!".format(pkg, branch.name))
      except git.exc.GitCommandError:
        valid = False
        printWithStyle(Style.Warning, "\033[K{} has no upstream configured for branch {}!".format(pkg, branch.name))
    if not valid:
      if args.verbose: print("\033[K{} not removable because it has unpushed commits.".format(repo_ws_path))
      continue

    # Check for debian package
    if not args.no_debs:
      # Try to resolve
      try:
        dep = rosdep_view.lookup(pkg)
      except (rosdep2.ResolutionError, KeyError):
        # Could not resolve pkg
        if args.verbose: print("\033[K{} not removable because rosdep could not find an entry for {}.".format(repo_ws_path, pkg))
        continue
      rosdep_result = dep.get_rule_for_platform(rosdep_os_name, rosdep_os_version, ["apt"], "apt")

      if rosdep_result is None or rosdep_result[0] != "apt":
        # No binary available
        if args.verbose: print("\033[K{} not removable because rosdep could not find a debian package for {}.".format(repo_ws_path, pkg))
        continue
      apt_pkgs = rosdep_apt_installer.resolve(rosdep_result[1])
      if len(apt_pkgs) != 1:
        # More than one binary, not sure if possible
        if args.verbose: print("\033[K{} not removable because rosdep resolved multiple debian packages for {} and this is not currently handled. Please create an issue.".format(repo_ws_path, pkg))
        continue
      binary_key = apt_pkgs[0]
      if binary_key not in apt_cache:
        # No binary available
        if args.verbose: print("\033[K{} not removable because the debian package for {} is not in the apt cache (try apt update).".format(repo_ws_path, pkg))
        continue

      binary_pkg = apt_cache[binary_key]
      repo_state.binaries[pkg] = binary_pkg

      git_commit_match = git_commit_id_regex.match(str(binary_pkg.versions[0].version))
      git_info = git_info_regex.match(str(binary_pkg.versions[0].homepage))
      if git_info is None or git_commit_match is None:
        # Can't determine if same state
        if args.verbose: print("\033[K{} not removable because I could not detect whether {} is on the same state as the debian package.".format(repo_ws_path, pkg))
        continue
      binary_branch = git_info.group(2)
      binary_commit = git_commit_match.group(1)

      local_branch = repo.active_branch.name
      local_commit = repo.git.rev_parse("HEAD", short=len(binary_commit))

      if binary_branch != local_branch or binary_commit != local_commit:
        # Not the same state
        if args.verbose: print("\033[K{} not removable because the debian package for {} is built using a different branch or HEAD.".format(repo_ws_path, pkg))
        continue

    # Repo is not dirty
    repo_state.clean = True
  print("\033[KDone.")

  replaceable = [item for item in git_repos.iteritems() if item[1].clean]
  if len(replaceable) == 0:
    printWithStyle(Style.Info, "Nothing to replace. Run again with -v (or --verbose) to find out why.")
    exit(0)

  selected = multiselect([(path, state.pkgs) for path, state in replaceable], "Replace", "Are you sure you don't want to replace any packages")
  if sum(selected) == 0:
    exit(0)

  # Now replace what was selected
  os.chdir(ws_root)
  pkgs_to_clean = []
  for i, item in enumerate(replaceable):
    if not selected[i]:
      continue
    path, state = item
    result = 0
    printWithStyle(Style.Info, ">>> Replacing {}...".format(path))
    if not args.no_debs:
      install_args = ["sudo", "apt", "install", "-y"]
      for pkg in state.pkgs:
        # Check if installed
        if not state.binaries[pkg].is_installed:
          # Install
          install_args.append(state.binaries[pkg].name)
      if len(install_args) > 3:
        result = subprocess.call(install_args)
        if result != 0:
          printWithStyle(Style.Error, "Could not install {}. Did not replace '{}'!".format(state.binaries[pkg].name, path))
          continue
      else:
        printWithStyle(Style.Success, "All required packages already installed!")
    pkgs_to_clean += state.pkgs
    
    print("Deleting {}...".format(path))
    if "/../" in path:
      printWithStyle(Style.Error, "Refusing to delete '{}'! Relative paths are not allowed!".format(path))
      continue
    if subprocess.call(["wstool", "remove", path]) != 0:
      printWithStyle(Style.Error, "Failed to remove from wstool")
    rmtree(os.path.join(ws_root, path))
    printWithStyle(Style.Info, "Deleted {}.".format(path))
  
  if len(pkgs_to_clean) != 0:
    printWithStyle(Style.Info, "Cleaning workspace...")
    if subprocess.call(["catkin", "clean"] + pkgs_to_clean) != 0:
      printWithStyle(Style.Error, "Cleaning failed! Your workspace may be dirty!")
      exit(1)
  
  printWithStyle(Style.Success, "All done!")
