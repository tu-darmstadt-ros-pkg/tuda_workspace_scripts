cmake_minimum_required(VERSION 3.5)
project(tuda_workspace_scripts)

find_package(ament_cmake REQUIRED)

if (WIN32)
  message(FATAL_ERROR "Windows is currently not supported! Feel free to add support :)")
else()
  ament_environment_hooks(env_hooks/10.setup.dsv.in)
  ament_environment_hooks(env_hooks/30.discovery_server.bash)
  ament_environment_hooks(env_hooks/50.command.bash.in)
  ament_environment_hooks(env_hooks/80.init.bash)
endif()

ament_python_install_package(${PROJECT_NAME})

install(DIRECTORY docker scripts DESTINATION share/${PROJECT_NAME} USE_SOURCE_PERMISSIONS)
install(FILES config.yaml DESTINATION share/${PROJECT_NAME})

ament_package()
