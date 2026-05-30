#!/usr/bin/env python3
import os
import sys
import argparse
import configparser
import asyncio
import pyudev
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog
from textual.containers import Vertical
from textual.worker import get_current_worker
from textual import work
import psutil

from robot import *

HOMED = False

def parse_config_and_args():
    parser = argparse.ArgumentParser(description="Klipper Textual Pipe Controller")
    parser.add_argument("-c", "--config", default="config.ini", help="Path to INI file")
    parser.add_argument("-p", "--pipe", help="Override Klipper named pipe path")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    if os.path.exists(args.config):
        config.read(args.config)
    
    pipe_path = args.pipe if args.pipe else config.get("klipper", "pipe_path", fallback="/tmp/printer")

    read_robot_config(config)

    return pipe_path

class TextualRobotnik(App):
    CSS = """
    Vertical {
        margin: 1 2;
    }
    RichLog {
        background: #000;
        color: #888;
        border: solid ;
        height: 1fr;
        margin-bottom: 1;
    }
    Input {
        dock: bottom;
        border: tall ;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit Application"),
        ("ctrl+c", "quit", "Quit")
    ]

    def __init__(self, pipe_path: str):
        super().__init__()
        self.pipe_path = pipe_path
        self.pipe_fd = None
        self.pipe_writer = None
        self.read_buffer = ""
        self.log_history = []
        self.log_repeats = 0

    def log_write(self, message: str) -> None:
        log_widget = self.query_one(RichLog)
        if self.log_history and len(self.log_history) > 0 and self.log_history[-1] == message:
            self.log_repeats += 1
            self.log_update(message, self.log_repeats)
        else:
            self.log_repeats = 0
            self.log_history.append(message)
            log_widget.write(message)

    def log_update(self, message: str, repeats: int = 0) -> None:
        log_widget = self.query_one(RichLog)
        if self.log_history:
            self.log_history.pop()
            self.log_history.append(message)
            log_widget.clear()
            for line in self.log_history[:-1]:
                log_widget.write(line)
            if repeats:
                log_widget.write(f"{message} [bold cyan]({repeats + 1}x)[/bold cyan]")
            else:
                log_widget.write(message)


    def log_commands_help(self):
        macros = ' '.join([x for x in robot_macros])
        self.log_write(f"[bold green][+][/bold green] MACROS: [bold yellow]{macros}[/bold yellow]")
        cmds = ' '.join([x for x in robot_commands.keys()])
        self.log_write(f"[bold green][+][/bold green] COMMANDS: [bold yellow]{cmds}[/bold yellow]")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield RichLog(highlight=True, markup=True, max_lines=1000)
            yield Input(placeholder="Type G-code or macro , (e.g., G28, GET_POSITION, CHECK_HOMED, PUT slot, GET slot, GRIPOR_OPEN, GRIPOR_CLOSE) and press Enter...")
        yield Footer()

    def on_mount(self) -> None:
        self.log_write("[bold green][+][/bold green] Starting TUI environment...")

        # 1. Open the non-blocking read descriptor
        try:
            self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
            self.log_write(f"[bold green][+][/bold green] Connected to read pipe: {self.pipe_path}")
        except OSError as e:
            self.log_write(f"[bold red][-] Failed to open read pipe:[/bold red] {e}")
            return

        self.log_write(f"[bold green][+][/bold green] READER={robot_get_reader_pos()} SPEED_FULL={robot_get_speed_full()} SLOTS={robot_get_slots()}")
        self.log_write(f"[bold green][+][/bold green] BLOCK_DEVICE={robot_get_block_device()}")
        self.log_commands_help()

        robot_set_logger(self.log_write)


        # udev monitor
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='block')
        self.monitor.start()
        udev_fd = self.monitor.fileno()
        loop = asyncio.get_running_loop()
        loop.add_reader(udev_fd, self.handle_udev_read)

        self.log_write("[green][+][/green] Hardware hotplug subsystem online.")

        # 2. Open the write stream channel
        try:
            self.pipe_writer = open(self.pipe_path, "w", encoding="utf-8", buffering=1)

            # immediately query homed status
            if self.pipe_writer:
                try:
                    self.pipe_writer.write(f"CHECK_HOMED\n")
                    self.pipe_writer.flush()
                except OSError as e:
                    self.log_write(f"[bold red][-] Write failure down active pipe matrix:[/bold red] {e}")
            else:
                self.log_write("[bold red][-] Connection writing pipe context unavailable.[/bold red]")

        except OSError as e:
            self.log_write(f"[bold red][-] Failed to open write pipe:[/bold red] {e}")
            return

        # klipper pipe
        loop = asyncio.get_running_loop()
        loop.add_reader(self.pipe_fd, self.handle_pipe_read)
        self.log_write("[bold green][+][/bold green] Async loop stream processing engine attached.")

		# volumes monitor
        self.track_volumes()

    def handle_pipe_read(self) -> None:
        try:
            ready_data = os.read(self.pipe_fd, 4096)
            if ready_data:
                self.read_buffer += ready_data.decode('utf-8', errors='replace')
                while "\n" in self.read_buffer:
                    line, self.read_buffer = self.read_buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        # Append directly into our scrollable TUI panel log view
                        self.log_write(f"[cyan][KLIPPER][/cyan] {line}")
                        if line.find("AXIS_STATUS: READY") != -1:
                            HOMED = True
                        if line.find("AXIS_STATUS: UNHOMED") != -1:
                            HOMED = False
                            self.send_command("G28")
                        if line.find("Must home axes first") != -1:
                            HOMED = False
                            self.send_command("G28")
        except BlockingIOError:
            pass # does it even happen? 
        except OSError as e:
            self.log_write(f"[bold red][-] Run-time read exception encountered:[/bold red] {e}")

    def send_command(self, cmd: str) -> None:
        cmd = cmd.strip()
        if not cmd:
            return

        if self.pipe_writer:
            try:
                self.pipe_writer.write(f"{cmd}\n")
                self.pipe_writer.flush()
            except OSError as e:
                self.log_write(f"[bold red][-] Write failure down active pipe: [/bold red] {e}")
        else:
            self.log_write("[bold red][-] Connection writing pipe context unavailable.[/bold red]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        input_widget = self.query_one(Input)

        if not cmd:
            return

        if cmd.lower() in ['exit', 'quit', 'feckov', 'feckoff']:
            self.exit()
            return

        cmdproc = False
        try:
            cmdproc = robot_commands[cmd.lower().split()[0]]
            self.log_write(f"cmdproc={cmdproc}")
            if cmdproc:
                cmd = cmdproc(cmd.split())
        except Exception as e:
            self.log_write(f"Exception in cmdproc: {e}")

        self.log_write(f"[bold magenta]>>> {cmd}[/bold magenta]")
        
        input_widget.value = ""

        self.send_command(cmd)

    def on_unmount(self) -> None:
        if self.pipe_fd is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.remove_reader(self.pipe_fd)
                os.close(self.pipe_fd)
            except Exception:
                pass
        if self.pipe_writer:
            try:
                self.pipe_writer.close()
            except Exception:
                pass
        if hasattr(self, 'observer'):
            self.observer.stop()

    def handle_udev_read(self) -> None:
        device = self.monitor.poll(timeout=0)

        #self.log_write(f"[bold green][+ UDEV][/bold green] Node: {device.device_node} Action: {device.action} robot.bd: {BLOCK_DEVICE}")
        if device and BLOCK_DEVICE in device.device_node:
            action = device.action # 'add', 'remove', or 'change'
            
            if action == "add":
                self.log_write(f"[bold green][+ CARD ADD][/bold green] Node: {device.device_node}")
            elif action == "remove":
                self.log_write(f"[bold red][- CARD REMOVE][/bold red] Node: {device.device_node}")
            elif action == "change":
                self.log_write(f"[bold red][- CARD CHANGE][/bold red] Node: {device.device_node}")

    @work(thread=True, exclusive=True)
    def track_volumes(self) -> None:
        # Get initial snapshot
        try:
            last_parts = {p.mountpoint: p.device for p in psutil.disk_partitions(all=False)}
            self.call_from_thread(self.log_write, f"last_parts={repr(last_parts)}")
        except Exception as e:
            self.call_from_thread(self.log_write, f"ininital Exception: {e}")
            last_parts = {}

        worker = get_current_worker()
        while not worker.is_cancelled:
            time.sleep(2.0)
            
            #self.call_from_thread(self.log_write, "worker is not cancelled...")
            
            try:
                current_parts = {p.mountpoint: p.device for p in psutil.disk_partitions(all=False)}
                #self.call_from_thread(self.log_write, f"current_parts={repr(current_parts)}")
            except Exception as e:
                self.call_from_thread(self.log_write, f"in loop Exception: {e}")
                continue

            # Check for mounts
            for mountpoint, device in current_parts.items():
                if mountpoint not in last_parts:
                    self.call_from_thread(self.log_write, f"MOUNTED {device} {mountpoint}")

            # Check for dismounts
            for mountpoint, device in last_parts.items():
                if mountpoint not in current_parts:
                    self.call_from_thread(self.log_write, f"DISMOUNTED {device} {mountpoint}")
            last_parts = current_parts

if __name__ == "__main__":
    target_pipe = parse_config_and_args()
    app = TextualRobotnik(pipe_path=target_pipe)
    app.run()
