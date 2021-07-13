#!/bin/bash

if [ ! -f "/tmp/remote-sim.master" ]; then
  echo "Failed to find remote sim master."
  echo "Did you run the remote_sim command?"
  exit 1
fi

_TMP_REMOTE_SIM_MASTER=$(cat /tmp/remote-sim.master)
_TMP_REMOTE_SIM_IP=$(ip -br a show $(cat /tmp/remote-sim.device) primary | tr -s ' ' | cut -d' ' -f3 | cut -d'/' -f1)

export GAZEBO_MASTER_URI=http://${_TMP_REMOTE_SIM_MASTER}:11345
echo_note "Set GAZEBO_MASTER_URI to ${GAZEBO_URI}"
export ROS_MASTER_URI=http://${_TMP_REMOTE_SIM_MASTER}:11311
echo_note "Set ROS_MASTER_URI to ${ROS_MASTER_URI}"
export GAZEBO_IP=${_TMP_REMOTE_SIM_IP}
export ROS_IP=${_TMP_REMOTE_SIM_IP}
echo_note "Set GAZEBO_IP and ROS_IP to ${ROS_IP}"

unset _TMP_REMOTE_SIM_MASTER
unset _TMP_REMOTE_SIM_IP
