#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
import argparse
try:
  import argcomplete
  __argcomplete = True
except ImportError:
  __argcomplete = False
import json
import os
import random
import re
import signal
import subprocess
import socket
from threading import Thread
import time
import traceback
import sys

HOSTNAMES = ['ball', 'burnell', 'chatelet', 'dalton', 'farnsworth',
             'feynman', 'foote', 'franklin', 'goodall', 'goodenough',
             'johnson', 'meitner', 'neumann', 'noether', 'samos']

CONNECTIONS = {}

def get_hostname(client):
  random.shuffle(HOSTNAMES)
  for hostname in HOSTNAMES:
    try:
      client.containers.get(hostname)
    except:
      return hostname
  return None

def send(conn, obj):
  conn.send(json.dumps(obj).encode('utf-8'))

def receive(conn):
  data = conn.recv(32768)
  if data == b'': return None
  try:
    return json.loads(data) if data is not None else None
  except json.JSONDecodeError as e:
    print(f"Couldn't parse: {data}")
    print(e)
    return None

def receive_print(conn, file=sys.stdout):
  while True:
    data = conn.recv(1024)
    if not data or len(data) == 0: break
    print(data.decode('utf-8'), end='', file=file)

def close_socket(s):
  try:
    s.shutdown(socket.SHUT_RDWR)
    s.close()
  except OSError:
    pass

def find_roslaunch(process):
  if process.name() == 'roslaunch':
    return process
  for c in process.children():
    result = find_roslaunch(c)
    if result is not None: return result
  return None

def handle_user(remote, conn, hostname):
  import docker
  import psutil
  client = docker.from_env()
  sim_process = None
  stdout_socket = None
  stderr_socket = None
  while True:
    try:
      request = receive(conn)
      if request is None: break
      if 'action' not in request:
        send(conn, {
          'success': False,
          'message': 'No action provided'
        })
      elif request['action'] == 'start':
        if sim_process is not None and sim_process.poll() is not None:
          try:
            container = docker.containers.get(hostname)
            container.kill()
          except docker.errors.NotFound:
            pass
        # Connect stdout
        stdout_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stdout_socket.connect((remote, request['stdout']))
        stdout = stdout_socket.makefile('wb', buffering=None)
        # Connect stderr
        stderr_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        stderr_socket.connect((remote, request['stderr']))
        stderr = stderr_socket.makefile('wb', buffering=None)
        # Start process
        envs = request.get('envs', {})
        env_args = list(map(lambda name: f'-e {name}="{envs[name]}"', envs.keys()))
        sim_process = subprocess.Popen(['/usr/bin/docker', 'run', '--rm'] + env_args + ['--net=docker-net', f'--hostname={hostname}.hector.lan', f'--name={hostname}', 'hector-noetic'],
                                        stdout=stdout, stderr=stderr)
        CONNECTIONS[hostname] = {'stdout': stdout_socket, 'stderr': stderr_socket, 'conn': conn}
        print(f"Started {hostname}")
        send(conn, {'success': True})
      elif request['action'] == 'stop':
        if sim_process is None:
          send(conn, {
            'success': False,
            'message': 'No simulation running!'
          })
          continue
        print(f"Requested stop of {hostname}")
        try:
          pid = client.api.inspect_container(hostname)['State']['Pid']
          process = find_roslaunch(psutil.Process(pid))
          if process is not None:
            process.send_signal(signal.SIGINT)
            sim_process.wait(30)
          else:
            print("Could not find process. Killing container")
            client.containers.get(hostname).kill()
        except docker.errors.NotFound:
          pass
        except:
          print(f"Didn't stop in 30s after SIGINT, killing container.")
          try:
            client.containers.get(hostname).kill()
          except docker.errors.NotFound:
            pass
          except:
            traceback.print_exc()
        print(f"{hostname} stopped.")
        CONNECTIONS[hostname]['stdout'] = None
        CONNECTIONS[hostname]['stderr'] = None
        close_socket(stdout_socket)
        close_socket(stderr_socket)
        send(conn, {
          'success': True
        })
      else:
        send(conn, {
          'success': False,
          'message': f'Unknown action: {request["action"]}'
        })
    except Exception as e:
      send(conn, {'success': False, 'message': repr(e)})
      traceback.print_exc()
  print(f"{remote} disconnected.")
  conn.close()

def host_server(ip, port):
  import docker
  import psutil
  client = docker.from_env()
  print('Starting DNS')
  try:
# nameserver: docker run --restart=unless-stopped -v /var/run/docker.sock:/var/run/docker.sock --net=docker-net defreitas/dns-proxy-server
    dns_container = client.containers.run('defreitas/dns-proxy-server',
                                          network='docker-net', volumes=['/var/run/docker.sock'],
                                          restart_policy={'Name': 'on-failure', 'MaximumRetryCount': 5},
                                          detach=True)
    network_settings = client.api.inspect_container(dns_container.name).get('NetworkSettings', {})
    nameserver = network_settings.get('Networks', {}).get('docker-net', {}).get('IPAddress', None)
    if nameserver is None:
      printWithStyle(Style.Error, 'Failed to get IP of DNS container!')
      exit(1)
  except:
    printWithStyle(Style.Error, 'Failed to start DNS container!')
    exit(1)
  print(f"DNS started on {nameserver}.")

  s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  s.bind((ip, port))
  print(f'Listening to {ip}:{port}')
  s.listen(4)
  hostnames = []
  threads = []
  while True:
    try:
      conn, addr = s.accept()
      print(f"{addr[0]} connected.")
      hostname = get_hostname(client)
      if hostname is None:
        send(conn, {'success': False, 'message': 'Failed to get a new hostname!'})
        close_socket(conn)
        continue
      send(conn, {'success': True, 'hostname': f'{hostname}.hector.lan', 'nameserver': nameserver})
      hostnames.append(hostname)
      t = Thread(target=handle_user, args=(addr[0], conn, hostname))
      t.start()
      threads.append(t)
    except KeyboardInterrupt:
      break
  print('Exit requested.')
  print('Killing docker containers')
  try:
    dns_container.kill()
  except:
    traceback.print_exc()
  for hostname in hostnames:
    try:
      client.containers.get(hostname).kill()
    except docker.errors.NotFound:
      pass
    except:
      traceback.print_exc()


  for key in CONNECTIONS:
    c = CONNECTIONS[key]
    if c['stdout'] is not None:
      close_socket(c['stdout'])
    if c['stderr'] is not None:
      close_socket(c['stderr'])
    close_socket(c['conn'])
  close_socket(s)
  print('Waiting for sockets to close.')
  for t in threads:
    t.join()


class Style:
  Error='\033[0;31m'
  Warning='\033[0;33m'
  Info='\033[0;34m'
  Success='\033[0;32m'
  Reset='\033[0;39m'

def printWithStyle(style, msg):
  print(style + msg + Style.Reset)

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--host', action='store_true', default=False, required=False, help='Hosts a simulation server on this machine.')
  parser.add_argument('--device', nargs='?', default='tun0', help='The network device used to reach the server. (Default: tun0)')
#  parser.add_argument('USER', nargs=1, help='The user to connect to the server via ssh.')
  server_arg = parser.add_argument('SERVER', nargs='?', default='10.8.0.1', help='IP of remote simulation server in VPN network. (Default: 10.8.0.1)')
  if __argcomplete:
    argcomplete.autocomplete(parser)

  args = parser.parse_args()

  server = args.SERVER
  if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', server) and not re.match(r'([a-f0-9:]+:+)+[a-f0-9]+', server):
    printWithStyle(Style.Error, f'Not a valid server ip: {server}')
    exit(1)

  if args.host:
    host_server(server, 23089)
  else:
    # Get my ip
    result = subprocess.run(f"ip -br a show {args.device} primary | tr -s ' ' | cut -d' ' -f3 | cut -d'/' -f1", stdout=subprocess.PIPE, shell=True)
    ip = result.stdout.decode('utf-8').strip()
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip) and not re.match(r'([a-f0-9:]+:+)+[a-f0-9]+', ip):
      printWithStyle(Style.Error, f'Failed to obtain IP, got: {server}')
      exit(1)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((server, 23089))
    response = receive(s)
    if 'success' not in response or not response['success']:
      printWithStyle(Style.Error, "Could not connect to remote server!")
      printWithStyle(Style.Error, f"Error: {response.get('message', 'Unknown error')}")
      exit(1)

    print("Connected. Setting up network.")

    # Write relevant information for master_remote_sim script
    with open('/tmp/remote-sim.master', 'w') as f:
      f.write(response['hostname'])
    with open('/tmp/remote-sim.device', 'w') as f:
      f.write(args.device)
    
    # Init network setup
    print(f'sudo resolvectl dns {args.device} {response["nameserver"]} && sudo resolvectl domain {args.device} "~hector.lan"')
    subprocess.run(f'sudo resolvectl dns {args.device} {response["nameserver"]} && sudo resolvectl domain {args.device} "~hector.lan"', shell=True)

    # Stdout and stderr sockets
    stdout_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stdout_socket.bind((ip, 0))
    stdout_socket.listen(1)

    stderr_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    stderr_socket.bind((ip, 0))
    stderr_socket.listen(1)

    # Get envs
    env_names = ['DEFAULT_ROBOT_TYPE', 'DEFAULT_ROBOT_ID', 'DEFAULT_SCENARIO_NAME', 'DEFAULT_ONBOARD_SETUP']
    workspace = os.environ.get('ROS_WORKSPACE', None)
    if workspace is None or not os.path.isfile(os.path.join(workspace, '../devel/setup.bash')):
      additional_envs = subprocess.run(['/bin/bash', '-c', 'source /opt/hector/setup.bash; _rosrs_setup_get_env_names'], stdout=subprocess.PIPE)
    else:
      additional_envs = subprocess.run(['/bin/bash', '-c', f'source {workspace}/../devel/setup.bash; _rosrs_setup_get_env_names'], stdout=subprocess.PIPE)
    env_names += additional_envs.stdout.decode('utf-8').split('\n')
    envs = {}
    for name in env_names:
      val = os.environ.get(name, None)
      if val is not None:
        envs[name] = val

    send(s, {'action': 'start', 'envs': envs, 'stdout': stdout_socket.getsockname()[1], 'stderr': stderr_socket.getsockname()[1]})
    response = receive(s)
    if response is None:
      printWithStyle(Style.Error, "Failed to get response from server!")
      exit(1)
    if not response['success']:
      printWithStyle(Style.Error, f'Error: {response.get("message", "Unknown error!")}')
      exit(1)
    
    # Print stdout and stderr continously
    stdout_conn, _ = stdout_socket.accept()
    stdout_thread = Thread(target=receive_print, args=(stdout_conn, sys.stdout))
    stdout_thread.start()
    stderr_conn, _ = stderr_socket.accept()
    stderr_thread = Thread(target=receive_print, args=(stderr_conn, sys.stderr))
    stderr_thread.start()

    try:
      while True:
        msg = receive(s)
        if msg is None: break
        if msg['action'] == 'shutdown': break
      printWithStyle(Style.Error, 'Remote is shutting down')
    except KeyboardInterrupt:
      send(s, {'action': 'stop'})
      s.settimeout(60)
      response = receive(s)
      if 'success' in response and response['success']:
        printWithStyle(Style.Info, "Remote simulation killed")
      else:
        printWithStyle(Style.Error, "Timeout: Remote simulation might still be running")
    close_socket(stdout_conn)
    close_socket(stderr_conn)
    close_socket(s)
    stdout_thread.join()
    stderr_thread.join()
