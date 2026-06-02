#!/usr/bin/env python3
import os
import sys
import argparse
import configparser
import asyncio
import pyudev
from functools import partial
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Button, Static, DirectoryTree
from textual.containers import Vertical, Horizontal
from textual.worker import get_current_worker
from textual import work
import psutil

from robot import *

HOMED = False
CARD_IN_GRIPOR = False

MOUNTED = 0
MOUNTED_UUID = ""

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

class Logger:
    def __init__(self, app, id):
        self.app = app
        self.id = id
        self.history = []
        self.repeats = 0
        self.max_lines = 200

    def write(self, message: str) -> None:
        log_widget = self.app.query_one(f"#{self.id}", RichLog)
        if self.history and len(self.history) > 0 and self.history[-1] == message:
            self.repeats += 1
            self.update(message, self.repeats)
        else:
            self.repeats = 0
            self.history.append(message)
            log_widget.write(message)
        self.history = self.history[:self.max_lines]

    def update(self, message: str, repeats: int = 0) -> None:
        log_widget = self.app.query_one(f"#{self.id}", RichLog)
        if self.history:
            self.history.pop()
            self.history.append(message)
            log_widget.clear()
            for line in self.history[:-1]:
                log_widget.write(line)
            if repeats:
                log_widget.write(f"{message} [bold cyan]({repeats + 1}x)[/bold cyan]")
            else:
                log_widget.write(message)

    

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
    Static {
        text-align: center;
    }
    Button.slot {
        background: #222;
    }
    Button.slot.present {
        background: orange;
        color: black;
    }
    Button.slot.busy {
        background: #777;
        color: white;
    }
    Button.slot.busy.blunk {
        background: yellow;
        color: black;
    }
    Button.slot.online {
        background: orange;
        color: black;
    }
    Button#dismount {
        background: red;
        color: yellow;
    }
    Button.service-button {
        background: #404;
        color: yellow;
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
        self.log_general = Logger(self, "general_log")
        self.log_klipper = Logger(self, "klipper_log")
        self.card_sensor_future = None

    def log_write(self, msg: str) -> None:
        self.log_general.write(msg)

    def log_commands_help(self):
        macros = ' '.join([x for x in robot_macros])
        self.log_write(f"[bold green][+][/bold green] MACROS: [bold yellow]{macros}[/bold yellow]")
        cmds = ' '.join([x for x in robot_commands.keys()])
        self.log_write(f"[bold green][+][/bold green] COMMANDS: [bold yellow]{cmds}[/bold yellow]")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            with Horizontal():
                yield RichLog(id="general_log", highlight=True, markup=True, max_lines=200)
                yield RichLog(id="klipper_log", highlight=True, markup=True, max_lines=200)
            with Horizontal():
                for n in range(12,0,-1):
                    with Vertical():
                        yield Static(f"Slot {n}", shrink=True)
                        yield Button("Check", id=f"check{n}", classes="slot")
                        yield Button("Mount", id=f"mount{n}", classes="mount-button")
                with Vertical():
                    yield Static("Reader", shrink=True)
                    yield Button("Rescan", id="btn-rescan", classes="slot online")
                    yield Button("Dismount", id="dismount", classes="mount", disabled=True)
            with Horizontal():
                yield Button("REHOME", id="svc-rehome", classes="service-button")
                yield Button("CHECK ALL", id="svc-check-all", classes="service-button")
                yield Button("ADJUST ALL", id="svc-adj-all", classes="service-button")
            yield Static(f"{robot_get_block_device()} on {robot_get_mount_point()}: {MOUNTED_UUID}", id="mount_label")
            yield DirectoryTree(robot_get_mount_point())


            yield Input(id="input", placeholder="Type G-code or macro , (e.g., G28, GET_POSITION, CHECK_HOMED, PUT slot, GET slot, GRIPOR_OPEN, GRIPOR_CLOSE) and press Enter...")
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
        self.log_write(f"[bold green][+][/bold green] BLOCK_DEVICE={robot_get_block_device()} MNT={robot_get_mount_point()}")
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

        # focus on the input field
        self.query_one(Input).focus()

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
                        #self.log_klipper.write(f"[cyan][KLIPPER][/cyan] {line}")
                        if line.find("AXIS_STATUS: READY") != -1:
                            HOMED = True
                        if line.find("AXIS_STATUS: UNHOMED") != -1:
                            HOMED = False
                            self.send_command("G28")
                        if line.find("Must home axes first") != -1:
                            HOMED = False
                            self.send_command("G28")
                        if self.card_sensor_future and not self.card_sensor_future.done():
                            if line.find("filament not detected") != -1:
                                CARD_IN_GRIPOR = False
                                self.card_sensor_future.set_result(False)
                                self.log_general("[cyan]PROBE[/cyan] No card in gripor")
                            if line.find("filament detected") != -1:
                                CARD_IN_GRIPOR = True
                                self.card_sensor_future.set_result(True)
                                self.log_general("[cyan]PROBE[/cyan] Card in gripor")
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
                self.log_klipper.write(f"[bold magenta]{cmd}[/bold magenta]")
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

        if cmd.lower().split()[0] == 'check':
            n,x = get_slot(cmd.lower().split())
            self.log_general.write(f"[cyan]Running check_slot_sequence()[/cyan]")
            self.check_slot_sequence(n)
            input_widget.value = ""
            return

        if cmd.lower().split()[0] == 'mount':
            n,x = get_slot(cmd.lower().split())
            self.log_general.write(f"[cyan]Running mount_slot_sequence()[/cyan]")
            self.mount_slot_sequence(n)
            input_widget.value = ""
            return
        
        if cmd.lower().split()[0] == 'dismount':
            self.log_general.write(f"[cyan]Running dismount_slot_sequence()[/cyan]")
            self.dismount_slot_sequence()
            input_widget.value = ""
            return

        cmdproc = False
        try:
            cmdproc = robot_commands[cmd.lower().split()[0]]
            if cmdproc:
                cmd = cmdproc(cmd.split())
        except Exception as e:
            self.log_write(f"Exception in cmdproc: {e}")

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
                self.set_timer(2.0, lambda: self.call_next(self.read_media_dir))
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
            
            try:
                current_parts = {p.mountpoint: p.device for p in psutil.disk_partitions(all=False)}
            except Exception as e:
                self.call_from_thread(self.log_write, f"in loop Exception: {e}")
                continue

            # Check for mounts
            for mountpoint, device in current_parts.items():
                if mountpoint not in last_parts:
                    self.call_from_thread(self.device_mounted, device, mountpoint)

            # Check for dismounts
            for mountpoint, device in last_parts.items():
                if mountpoint not in current_parts:
                    self.call_from_thread(self.device_dismounted, device, mountpoint)
            last_parts = current_parts

    def device_mounted(self, device: str, mountpoint: str) -> None:
        global MOUNTED_UUID
        if device == robot_get_block_device():
            context = pyudev.Context()
            udev_device = pyudev.Devices.from_device_file(context, robot_get_block_device())
            label = udev_device.get("ID_FS_LABEL", None)
            if label == None:
                label = udev_device.get("ID_FS_UUID", "")
            MOUNTED_UUID = label
            self.log_general.write(f"MOUNTED {device} {mountpoint} {MOUNTED_UUID}")
            stat = self.query_one("#mount_label", Static)
            stat.update(f"{robot_get_block_device()} on {robot_get_mount_point()}: {MOUNTED_UUID}")

    def device_dismounted(self, device: str, mountpoint: str) -> None:
        global MOUNTED_UUID
        if device == robot_get_block_device():
            self.log_general.write(f"DISMOUNTED {MOUNTED_UUID}")
            MOUNTED_UUID = ""
            stat = self.query_one("#mount_label", Static)
            stat.update(f"{robot_get_block_device()} on {robot_get_mount_point()}: NO VOLUME")

    @work(exclusive=True)
    async def check_slot_sequence(self, slots=0):
        try:
            lslots = list(slots)
        except:
            if slots == -1:
                lslots = range(1, 1 + len(robot_get_slots()))
            else:
                lslots = [slots]
        #raise Exception(f"lslots={lslots}")

        lslots = [int(x) for x in lslots]
        for n in lslots:
            self.set_card_busy(n, busy=True)
            self.send_command(cmd_get(['get', n]))
            await asyncio.sleep(0.2)
            self.send_command(move_to_slot(['slot', 0]))
            await asyncio.sleep(0.2)
            self.card_sensor_future = asyncio.get_running_loop().create_future()
            self.send_command("M400\nQUERY_FILAMENT_SENSOR SENSOR=card_sensor")
            #await asyncio.sleep(0.2)
            await self.card_sensor_future
            if self.card_sensor_future.result():
                self.log_general.write(f"[cyan][+][/cyan] Card present in slot {n}")
                self.send_command(cmd_put(['put', n]))
                self.set_card_present(n, present=True)
            else:
                self.send_command("GRIPOR_OPEN")
                self.set_card_present(n, present=False)
            self.set_card_busy(n, busy=False)

    @work(exclusive=True)
    async def adjust_slot_sequence(self, slots=0):
        try:
            lslots = list(slots)
        except:
            if slots == -1:
                lslots = range(1, 1 + len(robot_get_slots()))
            else:
                lslots = [slots]

        self.send_command("GRIPOR_CLOSE\nM400")
        lslots = [int(x) for x in lslots]
        for n in lslots:
            self.set_card_busy(n, busy=True)
            self.send_command(adjust_card_in_slot(['adjust', n]))
            self.set_card_busy(n, busy=False)
        self.send_command("GRIPOR_OPEN")


    def set_card_busy(self, slot, busy=True):
        if slot > 0:
            check_btn = self.query_one(f"#check{slot}")
            self.blinker = self.set_interval(0.5, partial(self.busy_animation, check_btn))
            if busy:
                check_btn.add_class("busy")
            else:
                if self.blinker != None:
                    self.blinker.stop()
                    self.blinker = None
                check_btn.remove_class("blunk")
                check_btn.remove_class("busy")

    def set_card_present(self, slot, present=True):
        if slot > 0:
            check_btn = self.query_one(f"#check{slot}")
            if present:
                check_btn.add_class("present")
                check_btn.label = "Present"
            else:
                check_btn.remove_class("present")
                check_btn.label = "Check"

    def disable_mount_buttons(self, disable: bool) -> None:
        for patonki in self.query('.mount-button'):
            patonki.disabled = disable

    @work(exclusive=True)
    async def mount_slot_sequence(self, slot=0):
        global MOUNTED
        slot = int(slot)
        if MOUNTED != 0 and MOUNTED != slot:
            self.log_general.write(f"[red][+][/red] Card {MOUNTED} is mounted, dismount first.")
            return

        if MOUNTED == slot:
            self.log_general.write(f"[red][+][/red] Card already mounted.")
            return

        self.disable_mount_buttons(disable=True)

        n = slot
        self.set_card_busy(slot, busy=True)
        dismo_btn = self.query_one(f"#dismount")

        self.send_command(cmd_get(['get', n]))
        await asyncio.sleep(0.2)
        self.send_command(move_to_slot(['slot', 0]))
        await asyncio.sleep(0.2)
        self.card_sensor_future = asyncio.get_running_loop().create_future()
        self.send_command("M400\nQUERY_FILAMENT_SENSOR SENSOR=card_sensor")
        await self.card_sensor_future
        if self.card_sensor_future.result():
            self.log_general.write(f"[cyan][+][/cyan] Card in gripor")
            self.send_command(cmd_put(['put', 0]))
            self.set_card_present(slot, present=True)
            dismo_btn.disabled = False
            MOUNTED = n
        else:
            self.log_general.write(f"[red][+][/red] No card")
            self.send_command("GRIPOR_OPEN")
            self.set_card_present(slot, present=False)
            self.disable_mount_buttons(disable=false)
        self.set_card_busy(slot, busy=False)

    @work(exclusive=True)
    async def dismount_slot_sequence(self):
        global MOUNTED
        if MOUNTED == 0:
            self.log_general.write(f"[red][+][/red] Not mounted.")
            return

        dismo_btn = self.query_one(f"#dismount")
        dismo_btn.disabled = True

        self.send_command(cmd_get(['get', 0]))
        await asyncio.sleep(0.2)
        self.send_command(cmd_put(['put', MOUNTED]))
        await asyncio.sleep(0.2)
        MOUNTED = 0
        self.disable_mount_buttons(disable=False)


    def busy_animation(self, btn):
        if btn.has_class("blunk"):
            btn.remove_class("blunk")
        else:
            btn.add_class("blunk")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        self.log_general.write(f"on_button_pressed id={event.button.id}")
        if event.button.id.startswith("check"):
            slot = event.button.id[len("check"):]
            self.check_slot_sequence(slots=[slot])
        if event.button.id.startswith("mount"):
            slot = int(event.button.id[len("mount"):])
            self.mount_slot_sequence(slot)
        if event.button.id.startswith("dismount"):
            self.dismount_slot_sequence()
        if event.button.id == "btn-rescan":
            self.read_media_dir()
        if event.button.id == "svc-rehome":
            self.send_command("G28")
        if event.button.id == "svc-check-all":
            self.check_slot_sequence(-1)
        if event.button.id == "svc-adj-all":
            self.adjust_slot_sequence(-1)

    async def read_media_dir(self) -> None:
        try:
            files = await asyncio.to_thread(os.listdir, robot_get_mount_point())
            self.query_one(DirectoryTree).reload()
            self.log_write(f"[bold cyan]Files:[/bold cyan] {' '.join(files)}")
        except OSError:
            self.notify("Drive was not ready", severity="error")

if __name__ == "__main__":
    target_pipe = parse_config_and_args()
    app = TextualRobotnik(pipe_path=target_pipe)
    app.run()
