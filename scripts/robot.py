#!/usr/bin/env python3

import os
import sys
import time
import threading
import argparse
import configparser

CARD_X = 5
CARD_Y = 23
Y_FULL_RETRACT = 4      # safe Y to move gripor with card
Y_ADJ_RETRACT = 13      # for moving without card
CARD_Y_INSERT = 23
CARD_Y_STORE = 18
SPEED_FULL = 18000
SLOTS = 27.5
BLOCK_DEVICE = "sda"
MOUNT_POINT = "/mnt/robot_media"

STATE = 0                   # 0 = homing check, 1,2 = homing loop, 10 = normal
SCRIPT_CMD = None
homing_start_time = 0

log_write = False

def parse_arguments():
    """Handle command line arguments and optional configuration overrides."""
    parser = argparse.ArgumentParser(
        description="Native Linux Pipe Controller Boilerplate for Klipper Interaction."
    )
    parser.add_argument(
        "-c", "--config", 
        default="config.ini", 
        help="Path to configuration INI file (default: config.ini)"
    )
    parser.add_argument(
        "-p", "--pipe", 
        help="Override Klipper named pipe path (default read from INI)"
    )
    parser.add_argument(
        "-v", "--verbose", 
        action="store_true", 
        help="Enable verbose debug logging output"
    )
    return parser.parse_args()

def load_configuration(config_path):
    """Load and parse the system INI configuration file safely."""
    config = configparser.ConfigParser()
    if not os.path.exists(config_path):
        print(f"[-] Configuration file missing: {config_path}", file=sys.stderr)
        sys.exit(1)
    config.read(config_path)
    return config

def homing_start():
    global STATE, homing_start_time
    STATE = 1
    homing_start_time = time.perf_counter()
    return "CHECK_HOMED"

def homing_loop(line):
    global STATE, SCRIPT_CMD
    #print(f"homing_loop: line=[{line}]")
    if STATE == 1:
        if line.find("AXIS_STATUS: READY") != -1:
            print(f"Axes are homed")
            STATE = 10
        if time.perf_counter() - homing_start_time > 0.5:
            SCRIPT_CMD = "G28" 
            STATE = 2
    elif STATE == 2:
        if line.find("ok") != -1:
            print(f"Homing done")
            STATE = 10

def pipe_read_worker(pipe_fd, stop_event):
    """Background worker thread that reads responses from the Klipper pipe."""
    print("[+] Pipe listener thread started.")
    buffer = ""

    global STATE
    
    while not stop_event.is_set():
        try:
            ready_data = os.read(pipe_fd, 4096)
            
            if ready_data:
                buffer += ready_data.decode('utf-8', errors='replace')
                
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        print(f"\n[KLIPPER] {line}\n>>> ", end="", flush=True)
                        if STATE in [1,2]:
                            homing_loop(line)
            else:
                time.sleep(0.05)
                
        except BlockingIOError:
            if STATE in [1,2]:
                homing_loop("")
            time.sleep(0.02)
        except OSError as e:
            print(f"\n[-] Pipe read error occurred: {e}", file=sys.stderr)
            stop_event.set()
            break

def robot_set_logger(loggor):
    global log_write
    log_write = loggor

def get_slot(args, cmd="get_slot_num"):
    slots = SLOTS
    if len(args) < 2:
        msg = f"{cmd}: missing slot number"
        log_write(msg) if log_write else print(msg, file=sys.stderr)
        return [-1, -1]
    try:
        n = int(args[1])
    except:
        msg = f"{cmd}: {args[1]} is not a slot number"
        log_write(msg) if log_write else print(msg, file=sys.stderr)
        return [-1, -1]

    if n < 0 or n > len(slots):
        msg =f"{cmd}: {n} not in range [0, {len(slots)}]"
        log_write(msg) if log_write else print(msg, file=sys.stderr)
        return [-1, -1]
    
    if n == 0:
        return [0, CARD_X]
    else:
        return [n, float(slots[n - 1])]


def move_to_slot(args):
    n, xpos = get_slot(args, "move_to_slot")
    if n >= 0 and xpos >= 0:
        return f"""
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
G1 X{xpos} F{SPEED_FULL}
M400
RESPOND TYPE=echo MSG="macro_complete:slot"
"""
    else:
        return ""


def get_from_reader():
    return f'''
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
GRIPOR_OPEN
G1 X{CARD_X} F{SPEED_FULL}
G1 Y{CARD_Y_INSERT}
G4 P100
GRIPOR_CLOSE
G1 Y{Y_FULL_RETRACT}
M400
RESPOND TYPE=echo MSG="macro_complete:get"
'''

def put_to_reader():
    return f'''
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
G1 X{CARD_X} F{SPEED_FULL}
G1 Y{CARD_Y_INSERT}
G4 P100
GRIPOR_OPEN
G1 Y14      ; retract to close the beak
M400
GRIPOR_CLOSE
G1 Y{CARD_Y_INSERT-2} F1000     ; push in
G4 P250
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
GRIPOR_OPEN
RESPOND TYPE=echo MSG="macro_complete:put"
'''

def move_to_slot_adj(args):
    n, xpos = get_slot(args, "move_to_slot")
    if n >= 0 and xpos >= 0:
        return f"""
G1 Y{Y_ADJ_RETRACT} F{SPEED_FULL}
G1 X{xpos} F{SPEED_FULL}
"""
    else:
        return ""

def adjust_card_in_slot(args):
    text = ''
    if len(args) > 1:
        text = move_to_slot_adj(args)
    return text + f'''
G1 Y{Y_ADJ_RETRACT} F{SPEED_FULL}
G1 Y{CARD_Y_STORE-3} F1000     ; push in slightly
G1 Y{Y_ADJ_RETRACT} F{SPEED_FULL/4}
M400
RESPOND TYPE=echo MSG="macro_complete:adjust"
'''

def put_to_store(args):
    text = ''
    if len(args) > 1:
        text = move_to_slot(args)

    return text + f'''
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
G1 Y{CARD_Y_STORE}
G4 P100
GRIPOR_OPEN

G1 Y14      ; retract to close the beak
GRIPOR_CLOSE
G1 Y{CARD_Y_STORE-3} F1000     ; push in slightly
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL/4}
GRIPOR_OPEN
RESPOND TYPE=echo MSG="macro_complete:put"
'''

def get_from_store(args):
    text = ''
    if len(args) > 1:
        text = move_to_slot(args)
    return text + f'''
G1 Y{Y_FULL_RETRACT} F{SPEED_FULL}
GRIPOR_OPEN
G4 P100
G1 Y{CARD_Y_STORE}
GRIPOR_CLOSE
G1 Y{Y_FULL_RETRACT}
M400
RESPOND TYPE=echo MSG="macro_complete:get"
'''

def cmd_get(args):
    n, xpos = get_slot(args)
    if n < 0:
        return ""
    elif n == 0:
        return get_from_reader()
    return get_from_store(args)

def cmd_put(args):
    n, xpos = get_slot(args)
    if n < 0:
        return ""
    elif n == 0:
        return put_to_reader()
    return put_to_store(args)


robot_commands = {
        'put': cmd_put,
        'get': cmd_get,
        'slot': move_to_slot,
        'adjust': adjust_card_in_slot
        }

robot_macros = (
        'CHECK_HOMED',
        'GRIPOR_OPEN',
        'GRIPOR_CLOSE')

def robot_get_slots():
    return SLOTS

def robot_get_reader_pos():
    return CARD_X, CARD_Y

def robot_get_speed_full():
    return SPEED_FULL

def robot_get_block_device():
    return BLOCK_DEVICE

def robot_get_mount_point():
    return MOUNT_POINT

def read_robot_config(config):
    global CARD_X, CARD_Y, CARD_Y_INSERT, CARD_Y_STORE, SPEED_FULL, SLOTS, BLOCK_DEVICE, MOUNT_POINT

    CARD_X = float(config.get("robot", "card_x", fallback=CARD_X))
    CARD_Y = float(config.get("robot", "card_y", fallback=CARD_Y))
    CARD_Y_INSERT = float(config.get("robot", "card_y_insert", fallback=CARD_Y_INSERT))
    CARD_Y_STORE = float(config.get("robot", "card_y_store", fallback=CARD_Y_STORE))
    SPEED_FULL = float(config.get("robot", "speed_full", fallback=SPEED_FULL))
    SLOTS = config.get("robot", "slots", fallback=SLOTS)
    SLOTS = [float(x) for x in SLOTS.split()[::-1]]

    BLOCK_DEVICE = config.get("robot", "block_device", fallback=BLOCK_DEVICE)
    MOUNT_POINT = config.get("robot", "mount_point", fallback=MOUNT_POINT)


def main():
    args = parse_arguments()
    config = load_configuration(args.config)

    pipe_path = args.pipe if args.pipe else config.get("klipper", "pipe_path", fallback="/tmp/printer")
    verbose = args.verbose or config.getboolean("app", "verbose", fallback=False)

    global CARD_X, CARD_Y, CARD_Y_INSERT, CARD_Y_STORE, SPEED_FULL, SLOTS

    read_robot_config(config)

    if verbose:
        print(f"[DEBUG] Target Pipe Path: {pipe_path}")

    try:
        pipe_fd = os.open(pipe_path, os.O_RDWR | os.O_NONBLOCK)
        print(f"[+] Established virtual file descriptor link on {pipe_path}")
    except OSError as e:
        print(f"[-] Failed to open Klipper pipe node: {e}", file=sys.stderr)
        sys.exit(1)

    stop_event = threading.Event()
    read_thread = threading.Thread(target=pipe_read_worker, args=(pipe_fd, stop_event), daemon=True)
    read_thread.start()

    print("\n=== Klipper Pipe Console Active ===")
    print("Type G-code or macro commands. Enter 'exit' or 'quit' to close safely.\n")

    global STATE, SCRIPT_CMD
    STATE = 0 # home-check
    SCRIPT_CMD = None
    
    try:
        while not stop_event.is_set():
            if STATE == 0:
                cmd = homing_start()
            elif STATE in [1,2]:
                if SCRIPT_CMD != None:
                    cmd = SCRIPT_CMD
                    SCRIPT_CMD = None
                else:
                    continue
            elif STATE == 10:
                cmd = input(">>> ").strip()
            
            if not cmd:
                continue
                
            if cmd.lower() in ['exit', 'quit', 'feckoff']:
                print("[+] Exiting...")
                break

            if cmd.lower().startswith('put '):
                cmd = cmd_put(cmd.split())
            elif cmd.lower().startswith('get '):
                cmd = cmd_get(cmd.split())
            elif cmd.lower() == 'get_from_reader':
                cmd = get_from_reader()
            elif cmd.lower() == 'put_to_reader':
                cmd = put_to_reader()
            elif cmd.lower().startswith('put_to_store'):
                cmd = put_to_store(cmd.split())
            elif cmd.lower().startswith('get_from_store'):
                cmd = get_from_store(cmd.split())
            elif cmd.lower().startswith('move_to_slot'):
                cmd = move_to_slot(cmd.split())

            try:
                payload = f"{cmd}\n".encode('utf-8')
                os.write(pipe_fd, payload)
            except OSError as e:
                print(f"[-] Write transmission failure to node: {e}", file=sys.stderr)
                break

    except (KeyboardInterrupt, SystemExit):
        print("\n[-] Session interrupted via signal signature.")
    finally:
        print("[+] Releasing file system descriptor paths...")
        stop_event.set()
        
        try:
            os.close(pipe_fd)
        except OSError:
            pass
            
        read_thread.join(timeout=1.0)
        print("[+] Application terminated cleanly.")

if __name__ == "__main__":
    print("Don't run this unless for testing, run tui.py")
    #main()
