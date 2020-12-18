cmake_minimum_required(VERSION 2.8.3)
project(tuda_workspace_scripts)

find_package(catkin REQUIRED)

catkin_package()

catkin_add_env_hooks(30.setup_tuda_workspace_scripts SHELLS bash)

#############
## Install ##
#############

# all install targets should use catkin DESTINATION variables
# See http://ros.org/doc/api/catkin/html/adv_user_guide/variables.html

install(DIRECTORY scripts/
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}/scripts
  USE_SOURCE_PERMISSIONS
)
