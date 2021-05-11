#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
# This script checks out a package only available as binary, if the homepage
# field follows the scheme ${GIT_REPO}#${BRANCH}

from __future__ import print_function
try:
  import apt
except ImportError:
  print("python3-apt is required! Install using 'sudo apt install python3-apt'")
  exit(1)
try:
  import git
except ImportError:
  print("GitPython is required! Install using 'pip3 install --user gitpython'")
  exit(1)
import argparse
try:
  import argcomplete
  __argcomplete = True
except ImportError:
  __argcomplete = False
import curses
import re
from rosdep2 import create_default_installer_context, get_default_installer
from rosdep2.lookup import RosdepLookup
from rosdep2.rospkg_loader import DEFAULT_VIEW_KEY
from rospkg import RosPack
import os
import sys

class Style:
  Error='\033[0;31m'
  Warning='\033[0;33m'
  Info='\033[0;34m'
  Success='\033[0;32m'
  Reset='\033[0;39m'

def printWithStyle(style, msg):
  print(style + msg + Style.Reset)
  

class PackageChoiceCompleter:
  def __init__(self, rospack):
    self.rospack = rospack

  def __call__(self, **kwargs):
    packages = self.rospack.list()
    return [pkg for pkg in packages]

class RosdepResolver:
  def __init__(self):
    self.installer_context = create_default_installer_context()
    _, self.installer_keys, self.default_key, self.os_name, self.os_version = get_default_installer(installer_context=self.installer_context)
    self.lookup = RosdepLookup.create_from_rospkg()
    self.rosdep_view = self.lookup.get_rosdep_view(DEFAULT_VIEW_KEY)

  def resolve_apt(self, pkg):
    try:
      dep = self.rosdep_view.lookup(pkg)
      rule_installer, rule = dep.get_rule_for_platform(self.os_name, self.os_version, self.installer_keys, self.default_key)
      if rule_installer != "apt":
        return None
      installer = self.installer_context.get_installer(rule_installer)
      pkgs = installer.resolve(rule)
      if len(pkgs) < 1:
        return None
      return pkgs
    except BaseException as e:
      printWithStyle(Style.Error, "Could not resolve apt for package {}. Exception: {}".format(pkg, repr(e)))
    return None


def selectPackages(stdscr, packages):
  search_string = ""
  valid_regex = re.compile("\w+")
  selection = packages[0]
  selected = []
  curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
  curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_GREEN)
  curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLUE)
  first_visible_row = 0
  enter_pressed_empty = False  # Set to true if enter pressed without selection to confirm before exit
  while True:
    stdscr.clear()
    ROWS, COLS = stdscr.getmaxyx()
    
    if ROWS > 5 and COLS > 14:
      if len(search_string) > 0:
        stdscr.addstr(0, 0, "Search:", curses.A_STANDOUT)
        stdscr.addstr(" " + search_string)
      else:
        stdscr.addstr(0, 0, "Type to search [Press Enter to finish]:", curses.A_STANDOUT)
      cursor_pos = stdscr.getyx()
      available_rows = ROWS - 1 - cursor_pos[0] - 4  # 2 border top and bottom

      filtered_packages = list(filter(lambda x: search_string in x, packages))
      if len(filtered_packages) > 0:
        if selection not in filtered_packages:
          selection = filtered_packages[0]
        positions = []
        col = 0
        row = 0
        for pkg in filtered_packages:
          if len(pkg) + col >= COLS:
            row += 2
            col = 0
          positions.append((row, col))
          col += len(pkg) + 2


        selected_index = filtered_packages.index(selection) if selection is not None else 0
        if positions[selected_index][0] < first_visible_row:
          first_visible_row = positions[selected_index][0]
        elif positions[selected_index][0] > first_visible_row + available_rows:
          first_visible_row = positions[selected_index][0] - available_rows

        offset_row = cursor_pos[0] + 2
        if first_visible_row > 0:
          stdscr.addstr(cursor_pos[0] + 1, 0, "...", curses.A_STANDOUT)

        for pos, pkg in zip(positions, filtered_packages):
          row, col = pos
          if row >= first_visible_row and row <= first_visible_row + available_rows:
            stdscr.move(offset_row + row - first_visible_row, col)
            attr = curses.A_STANDOUT
            if pkg in selected:
              attr = curses.color_pair(2 if pkg != selection else 3)
            elif pkg == selection:
              attr = curses.color_pair(1)
            stdscr.addstr(pkg if len(pkg) < COLS else pkg[0:COLS-4]+"...", attr)
            stdscr.addstr(" " * min(COLS - col - 1 - len(pkg), 2))

        if positions[-1][0] - first_visible_row > available_rows:
          stdscr.addstr(offset_row + available_rows + 1, 0, "...", curses.A_STANDOUT)

      if len(selected) == 0 and enter_pressed_empty:
        stdscr.addstr(ROWS-1, 0, "Press enter again to exit or space to add highlighted package"[0:COLS-1], curses.A_STANDOUT)
      elif len(selected) == 0:
        stdscr.addstr(ROWS-1, 0, "Press space to add highlighted package"[0:COLS-1], curses.A_STANDOUT)
      else:
        stdscr.addstr(ROWS-1, 0, "{} packages selected".format(len(selected))[0:COLS-1], curses.A_STANDOUT)

      stdscr.move(cursor_pos[0], cursor_pos[1])

    stdscr.refresh()
    try:
      user_input = stdscr.getkey()
    except KeyboardInterrupt:
      exit(0)
    
    if valid_regex.match(user_input) is not None and not user_input.startswith("KEY"):
      search_string += user_input
    elif user_input == "KEY_BACKSPACE":
      search_string = search_string[0:-1]
    elif "\n" in user_input:
      if len(selected) == 0:
        if enter_pressed_empty:
          break
        enter_pressed_empty = True
        continue
      break
    elif user_input == " " and len(filtered_packages) > 0:
      if selection in selected:
        selected.remove(selection)
      else:
        selected.append(selection)
    elif user_input == "KEY_RIGHT":
      selection = filtered_packages[(filtered_packages.index(selection) + 1) % len(filtered_packages)]
    elif user_input == "KEY_LEFT":
      selection = filtered_packages[(filtered_packages.index(selection) - 1) % len(filtered_packages)]
    elif user_input == "KEY_UP" or user_input == "KEY_DOWN":
      selected_index = filtered_packages.index(selection)
      center = (positions[selected_index][0], positions[selected_index][1] + len(selection) / 2)
      if user_input == "KEY_UP":
        row = center[0] - 2 if center[0] - 2 >= 0 else positions[-1][0]
      else:
        row = center[0] + 2 if center[0] + 2 <= positions[-1][0] else positions[0][0]
      closest = None
      for i, c in enumerate(positions):
        if c[0] != row:
          continue
        if closest is None or abs(positions[closest][1] + len(filtered_packages[closest]) / 2 - center[1]) > abs(c[1] + len(filtered_packages[i]) / 2 - center[1]):
          closest = i
      selection = filtered_packages[closest]

    enter_pressed_empty = False
  return selected


if __name__ == "__main__":
  ws_src_path = os.environ.get("ROS_WORKSPACE")
  roswss_prefix = os.environ.get("ROSWSS_PREFIX", "roswss")
  rospack = RosPack()

  parser = argparse.ArgumentParser(usage="{} checkout [packages]".format(roswss_prefix),
                                   description="Checks out one or multiple package(s) currently installed as binaries into your workspace.")
  package_arg = parser.add_argument("packages", nargs="*",
                                    help="Specify one or multiple packages to checkout. Non-interactive. If you don't specify a package interactive mode is started.")

  if __argcomplete:
    package_arg.completer = PackageChoiceCompleter(rospack)
    argcomplete.autocomplete(parser)
  args = parser.parse_args()

  print("Collecting information...", end='\r')
  sys.stdout.flush()
  rosdep_resolver = RosdepResolver()
  apt_cache = apt.Cache()
  git_info_regex = re.compile("(.*\.git)#(.*)")

  to_replace = args.packages or []
  if len(to_replace) == 0:
    # Collect packages that can be replaced
    can_be_replaced = []
    for pkg in rospack.list():
        path = rospack.get_path(pkg)
        if path.startswith(ws_src_path):
          continue
        pkgs = rosdep_resolver.resolve_apt(pkg)
        if pkgs is None:
          continue
        binary_key = pkgs[0]
        if not binary_key in apt_cache:
          continue
        binary = apt_cache[binary_key]

        git_info = git_info_regex.match(str(binary.versions[0].homepage))
        if git_info is None:
          continue
        can_be_replaced.append(pkg)

    if len(can_be_replaced) == 0:
      printWithStyle(Style.Error, "No packages found that could be replaced!")
      exit(1)
    
    to_replace = curses.wrapper(selectPackages, sorted(can_be_replaced))
    if len(to_replace) == 0:
      exit(0)
    
  success = True
  for package in to_replace:
    printWithStyle(Style.Info, ">>> Replacing {}".format(package))
    pkgs = rosdep_resolver.resolve_apt(package)
    if pkgs is None or len(pkgs) < 1:
      printWithStyle(Style.Error, "Could not find package '{}'!".format(package))
      success = False
      continue
    binary_key = pkgs[0]
    if binary_key not in apt_cache:
      printWithStyle(Style.Error, "Could not find debian package named '{}'!".format(binary_key))
      success = False
      continue

    git_info = git_info_regex.match(str(apt_cache[binary_key].versions[0].homepage))
    if git_info is None:
      printWithStyle(Style.Error, "Failed to locate git info for package {}!".format(binary_key))
      success = False
      continue
    repo_url = str(git_info.group(1))
    branch = git_info.group(2)
    printWithStyle(Style.Info, "Checking out branch '{}' from '{}'...".format(branch, repo_url))

    repo_info = re.match(".*/(.*)\.git", repo_url)
    if repo_info is None:
      printWithStyle(Style.Error, "Failed to extract repo name from: {}".format(repo_url))
      success = False
      continue
    repo_name = repo_info.group(1)
    
    os.chdir(ws_src_path)
    if os.path.isdir(repo_name):
      printWithStyle(Style.Error, "There is already a folder named '{}' in workspace src folder!".format(repo_name))
      success = False
      continue
    import subprocess
    result = subprocess.call(["wstool", "set", repo_name, "--git", repo_url, "-v", branch, "-u", "-y"])
    if result != 0:
      printWithStyle(Style.Error, "An error occured!")
      success = False
      continue
    printWithStyle(Style.Success, "{} installed!".format(package))
  printWithStyle(Style.Warning, "Please note that the installed packages will still be suggested until the next build and re-source.")

  if not success:
    exit(1)
