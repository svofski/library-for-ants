#!/usr/bin/env python3
import os
import sys
import argparse
import configparser
import asyncio
import pyudev
import re
from functools import partial
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Button, Static, DirectoryTree, Label
from textual.containers import Vertical, Horizontal, Middle, Center
from textual.worker import get_current_worker
from textual import work
from textual.color import Color
from textual_canvas import Canvas
import psutil
import png
from math import ceil, floor
from rich.text import Text

from robot import *

HOMED = False
CARD_IN_GRIPOR = False

MOUNTED = 0
MOUNTED_UUID = ""
PRESENT = []

GUI_COMMANDS = ['exit', 'quit', 'feckov', 'check', 'mount', 'dismount']

LOG_NADA =  "        "
LOG_INFO =  "[bold green]INFO[/bold green]    "
LOG_ERROR = "[bold red]ERROR[/bold red]   "
LOG_MEDIA = "[bold yellow]MEDIA[/bold yellow]   "
LOG_STATUS = "[cyan]STATUS[/cyan]  "
LOG_SENSOR = "[blue]SENSOR[/blue]  "

LOG_KLIPPER = "[cyan]KLIPPER[/cyan] "
LOG_COMMAND = "[blue]GCODE[/blue]   "

LOGO_W = 0
LOGO_H = 0
LOGO_BMP = []

SDCARD_ANS = "[]"
GRIPOR_OPEN_ANS = "|  |"
GRIPOR_CLOSED_ANS = " || "
THEME_BGCOLOR = (0,0,0)
GRIPOR_STATE_OPEN = 0
GRIPOR_STATE_CLOSED = 1

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

    global PRESENT
    PRESENT = [False] * (len(robot_get_slots()) + 1)

    return pipe_path

class Logger:
    def __init__(self, app, id):
        self.app = app
        self.id = id
        self.history = []
        self.repeats = 0
        self.max_lines = 200

    def write(self, message: str, prefix: str = LOG_NADA) -> None:
        message = prefix + message
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
    TITLE = "Library for Ants"
    SUB_TITLE = "Robotnik v0.1"
    CSS = """
    Vertical {
        margin: 1 2;
    }
    #with-canvas-container {
        height: 30;
        align-vertical: middle;
    }
    #with-canvas-container > Vertical {
    }
    #layout-row-1 {
        height: 14;
    }
    #main-buttons-row {
        height: 14;
    }
    #second-buttons-row {
        height: 5;
    }
    #logo {
        width: 14;
        height: 14;
    }
    #dir-header {
        height: 2;
        align: left top;
    }
    #mount_label {
        width: 40;
        max-width: 40;
    }
    #btn-rescan {
        background: $boost;
    }
    .sdcard-graphics {
        margin-top: 1;
    }
    .sdcard-graphics.present {
    }
    #gripor {
        overflow: hidden hidden;
        height: 4;
        width: 4;
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
        min-width: 8;
        width: 100%;
    }
    Button.mount-button {
        min-width: 8;
        width: 100%;
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
    Button.slot.busy.blunk:disabled {
        opacity: 100%;
        background: yellow;
        color: black;
    }
    Button.slot.online {
        background: orange;
        color: black;
    }
    Button#dismount {
        background: gray;
        color: black;
    }
    Button.service-button {
        background: gray;
        color: black;
        min-width: 8;
        margin: 1;
    }
    Button.service-button.abort-button {
        color: white;
        background: red;
    }
    .status-label {
        background: #222;
        color: gray;
        min-width: 30;
        height: 3;
        margin: 1;
        content-align: center middle;
        width: 1fr;
    }
    .status-label.active {
        background: orange;
        color: black;
    }
    #fart-container {
        width: 100%;
        height: 100%;
        position: relative; /* Allows child widgets to use absolute layout */
    }
    #card-number {
        color: $accent;
        text-style: bold;
        offset: 5 3;
        position: absolute;
        width: 0;
        background: rgb(40,40,40); /* same as sdcard body */
    }
    #card-number.present {
        width: 2;
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
        self.blinker = None
        self.gripor_anim_x = 0
        self.gripor_anim_x_end = 0
        self.gripor_slot_num = 0
        self.gripor_state = -1
        self.gripor_anim_timer = None
        self.gripor_anim_state_end = GRIPOR_STATE_OPEN

    def log_write(self, msg: str) -> None:
        self.log_general.write(msg)

    def log_commands_help(self):
        macros = ' '.join([x for x in robot_macros])
        self.log_general.write(f"MACROS: [bold yellow]{macros}[/bold yellow]", LOG_INFO)
        cmds = ' '.join([x for x in list(robot_commands.keys()) + GUI_COMMANDS])
        self.log_general.write(f"COMMANDS: [bold yellow]{cmds}[/bold yellow]", LOG_INFO)

    def compose(self) -> ComposeResult:
        self.sdcard_ansi = Text.from_ansi(ansi_to_truecolor(SDCARD_ANS, (0,0,0)))
        yield Header(show_clock=True)
        with Vertical():
            with Horizontal(id="with-canvas-container"):
                with Middle(id="canvas-wrapper"):
                    yield Canvas(LOGO_W, LOGO_H + (LOGO_H % 2), Color(0,0,0), id="logo")
                with Vertical():
                    with Horizontal(id="main-buttons-row"):
                        for n in range(12,0,-1):
                            with Vertical():
                                yield Static(f"Slot {n}", shrink=True)
                                yield Button("Check", id=f"check{n}", classes="slot")
                                yield Button("Mount", id=f"mount{n}", classes="mount-button")
                                yield Static(self.sdcard_ansi, id=f"sdcard{n}", classes="sdcard-graphics")
                        with Vertical():
                            yield Static("Reader", shrink=True)
                            yield Button("CHECK ALL", id="svc-check-all", classes="slot online")
                            yield Button("Dismount", id="dismount", classes="mount-button", disabled=True)
                            with Static(id="fart-container"):
                                yield Static(self.sdcard_ansi, id=f"sdcard0", classes="sdcard-graphics")
                                yield Static("", id="card-number")
                    yield Static("GRIPOR", id="gripor")
                    with Horizontal(id="second-buttons-row"):
                        yield Label("READY", id="svc-status", classes="status-label")
                        yield Button("ABORT", id="svc-abort", classes="service-button abort-button")
                        yield Button("REHOME", id="svc-rehome", classes="service-button")
                        yield Button("ADJUST ALL", id="svc-adj-all", classes="service-button")
            with Horizontal(id="dir-header"):
                yield Static(f"{robot_get_block_device()} on {robot_get_mount_point()}: {MOUNTED_UUID}", id="mount_label")
                yield Button("Rescan", id="btn-rescan", compact=True)
            yield DirectoryTree(robot_get_mount_point())
            with Horizontal(id="layout-row-1"):
                yield RichLog(id="general_log", highlight=True, markup=True, max_lines=200)
                yield RichLog(id="klipper_log", highlight=True, markup=True, max_lines=200)
            yield Input(id="input", placeholder="Type G-code or macro and press Enter...")
        yield Footer()

    def open_pipes(self):
        # read from klipper
        try:
            self.pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
            self.log_general.write(f"Connected to read pipe: {self.pipe_path}", LOG_INFO)
        except OSError as e:
            self.log_general.write(f"Failed to open read pipe: {e}", LOG_ERROR)
            return

        # write to klipper
        try:
            self.pipe_writer = open(self.pipe_path, "w", encoding="utf-8", buffering=1)
            # immediately query homed status
            #if self.pipe_writer:
            #    try:
            #        self.pipe_writer.write(f"STATUS\nCHECK_HOMED\n")
            #        self.pipe_writer.flush()
            #    except OSError as e:
            #        self.log_general.write(f"Write failure down active pipe matrix:[/bold red] {e}", LOG_ERROR)
            #        self.close_pipes()
            #        return
            #else:
            #    self.log_general.write("Connection writing pipe context unavailable.[/bold red]", LOG_ERROR)
            #    self.close_pipes()
            #    return

        except OSError as e:
            self.close_pipes()
            self.log_general.write(f"[bold red][-] Failed to open write pipe:[/bold red] {e}", LOG_ERROR)
            return

        # klipper async reader
        loop = asyncio.get_running_loop()
        loop.add_reader(self.pipe_fd, self.handle_pipe_read)

        if self.reopen_timer != None:
            self.reopen_timer.stop()
            self.reopen_timer = None

    def close_pipes(self) -> None:
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

    def draw_logo(self) -> None:
        canvas = self.query_one("#logo")
        parent_bg = self.query_one("#canvas-wrapper").background_colors[0]
        canvas.clear(parent_bg)

        color = Color.parse("orange")
        for y,r in enumerate(LOGO_BMP):
            for x in range(len(r)):
                if r[x] != 0:
                    canvas.set_pixel(x, y, color)

    def on_ready(self) -> None:
        global THEME_BGCOLOR
        self.draw_logo()
        bgcolor = self.query_one("#canvas-wrapper").background_colors[0].rgb
        THEME_BGCOLOR = bgcolor
        self.sdcard_ansi = Text.from_ansi(ansi_to_truecolor(SDCARD_ANS, bg=bgcolor, sd=(40,40,40), contacts=(170,85,0)))
        self.sdcard_ansi_disabled = Text.from_ansi(ansi_to_truecolor(SDCARD_ANS, bg=bgcolor, sd=(0,0,0), contacts=(30,30,30)))
        for sd in self.query('.sdcard-graphics'):
            sd.update(self.sdcard_ansi_disabled)

        self.on_resize()
        self.animate_gripor(0, state=GRIPOR_STATE_OPEN)

        #self.set_card_present(12)


    def on_resize(self) -> None:
        pass
        #buttons_row = self.query_one("#main-buttons-row")
        #self.log_general.write(f"buttons_row.width={buttons_row.content_size.width}")
        #gripor = self.query_one("#gripor")
        #gripor.styles.offset = (40, 0) #buttons_row.content_size.width - 8

    def on_mount(self) -> None:
        #self.draw_logo()
        self.reopen_timer = None
        self.ABORTED = False
        self.log_general.write(f"READER={robot_get_reader_pos()} SPEED_FULL={robot_get_speed_full()} |SLOTS|={len(robot_get_slots())}", LOG_INFO)

        self.log_general.write(f"BLOCK_DEVICE={robot_get_block_device()} MNT={robot_get_mount_point()}", LOG_INFO)
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

		# volumes monitor
        self.track_volumes()

        # focus on the input field
        self.query_one(Input).focus()
        self.open_pipes()

        self.disable_all_buttons(True)

        self.send_command("CHECK_HOMED")
        
    @work(exclusive=True)
    async def rehome(self) -> None:
        HOMED = False
        self.update_status("HOMING")
        self.disable_all_buttons(disable=True)
        await self.send_command_future("G28", "homing")
        self.update_status("READY")
        self.disable_all_buttons(disable=False)

    def handle_pipe_read(self) -> None:
        global HOMED, CARD_IN_GRIPOR

        try:
            ready_data = os.read(self.pipe_fd, 4096)
            if ready_data:
                self.read_buffer += ready_data.decode('utf-8', errors='replace')
                while "\n" in self.read_buffer:
                    line, self.read_buffer = self.read_buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        # Append directly into our scrollable TUI panel log view
                        if line != "ok":
                            self.log_klipper.write(line, LOG_KLIPPER)
                        if line.find("AXIS_STATUS: READY") != -1:
                            HOMED = True
                            self.update_status("READY")
                            self.disable_all_buttons(disable=False)
                        if line.find("AXIS_STATUS: UNHOMED") != -1:
                            self.rehome()
                        if line.find("Must home axes first") != -1:
                            self.rehome()
                        #if line.find("Klipper state: Ready") != -1:
                        #    self.send_command("CHECK_HOMED")
                        #    self.disable_all_buttons(disable=False)
                        if line.find("Lost communication with MCU") != -1 or line.find("Klipper state: Shutdown") != -1:
                            self.go_offline()
                            HOMED = False
                            CARD_IN_GRIPOR = False
                        if self.card_sensor_future and not self.card_sensor_future.done():
                            if line.find("filament not detected") != -1:
                                CARD_IN_GRIPOR = False
                                self.card_sensor_future.set_result(False)
                                self.log_general.write("No card in gripor", LOG_SENSOR)
                            if line.find("filament detected") != -1:
                                CARD_IN_GRIPOR = True
                                self.card_sensor_future.set_result(True)
                                self.log_general.write("Card in gripor", LOG_SENSOR)
                        if self.command_future and not self.command_future.done():
                            n = line.find("macro_complete:")
                            if n != -1:
                                which = line[n + len("macro_complete:"):]
                                if self.command_future.which == which:
                                    #self.log_general.write(f"macro_complete: set result = {which}")
                                    self.command_future.set_result(which)

        except Exception as wtf:
            self.log_general.write(traceback.format_exc())
        except BlockingIOError:
            pass # does it even happen?
        except OSError as e:
            self.log_general.write(f"Run-time read exception encountered: {e}", LOG_ERROR)

    def send_command(self, cmd: str) -> None:
        cmd = cmd.strip()
        if not cmd:
            return

        if self.pipe_writer:
            try:
                #self.log_klipper.write(cmd, LOG_COMMAND)
                self.pipe_writer.write(f"{cmd}\n")
                self.pipe_writer.flush()
            except OSError as e:
                self.log_general.write(f"Write failure down active pipe: {e}", LOG_ERROR)
        else:
            self.log_general.write("Connection writing pipe context unavailable.", LOG_ERROR)

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
            self.check_slot_sequence(n)
            input_widget.value = ""
            return

        if cmd.lower().split()[0] == 'mount':
            n,x = get_slot(cmd.lower().split())
            self.mount_slot_sequence(n)
            input_widget.value = ""
            return

        if cmd.lower().split()[0] == 'dismount':
            self.dismount_slot_sequence()
            input_widget.value = ""
            return

        cmdproc = False
        try:
            cmdproc = robot_commands[cmd.lower().split()[0]]
            if cmdproc:
                cmd = cmdproc(cmd.split())
        except Exception as e:
            self.log_general.write(f"Exception in cmdproc: {e}", LOG_ERROR)

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

        if device and BLOCK_DEVICE in device.device_node:
            action = device.action # 'add', 'remove', or 'change'

            if action == "add":
                self.log_general.write(f"CARD ADD Node: {device.device_node}", LOG_MEDIA)
                self.set_timer(2.0, lambda: self.call_next(self.read_media_dir))
            elif action == "remove":
                self.log_general.write(f"CARD REMOVE Node: {device.device_node}", LOG_MEDIA)
            elif action == "change":
                self.log_general.write(f"CARD REMOVE Node: {device.device_node}", LOG_MEDIA)

    @work(thread=True, exclusive=True)
    def track_volumes(self) -> None:
        # Get initial snapshot
        try:
            last_parts = {p.mountpoint: p.device for p in psutil.disk_partitions(all=False)}
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

    async def check_slot(self, n):
        self.update_status(f"CHECK SLOT {n}")
        self.set_card_busy(n, busy=True)
        self.animate_gripor(slot=n, state=GRIPOR_STATE_CLOSED)
        await self.send_command_future(cmd_get(['get', n]), 'get')
        self.animate_gripor(slot=0, state=GRIPOR_STATE_CLOSED)
        await self.send_command_future(move_to_slot(['slot', 0]), 'slot')
        
        self.card_sensor_future = asyncio.get_running_loop().create_future()
        self.send_command("M400\nQUERY_FILAMENT_SENSOR SENSOR=card_sensor")
        await self.card_sensor_future
        if self.card_sensor_future.result():
            self.log_general.write(f"Card present in slot {n}", LOG_MEDIA)
            self.animate_gripor(slot=n, state=GRIPOR_STATE_CLOSED)
            await self.send_command_future(cmd_put(['put', n]), 'put')
            self.set_card_present(n, present=True)
            self.animate_gripor(slot=n, state=GRIPOR_STATE_OPEN)
        else:
            self.send_command("GRIPOR_OPEN")
            self.set_card_present(n, present=False)
            self.animate_gripor(slot=0, state=GRIPOR_STATE_OPEN)
        self.set_card_busy(n, busy=False)

    @work(exclusive=True)
    async def check_slot_sequence(self, slots=0, stop_at_empty=False):
        global PRESENT
        try:
            lslots = list(slots)
        except:
            if slots == -1:
                lslots = range(1, 1 + len(robot_get_slots()))
            else:
                lslots = [slots]

        self.ABORTED = False
        self.disable_all_buttons(disable=True)
        self.activate_abort_button(activate=True)

        lslots = [int(x) for x in lslots]
        for n in lslots:
            if self.ABORTED:
                self.activate_abort_button(activate=False)
                break
            await self.check_slot(n)
            if stop_at_empty and PRESENT[n] == False:
                break

        self.update_status("READY")
        self.disable_all_buttons(disable=False)

    async def check_slot_sequence_fuu(self, slots=0, stop_at_empty=False):
        global PRESENT
        try:
            lslots = list(slots)
        except:
            if slots == -1:
                lslots = range(1, 1 + len(robot_get_slots()))
            else:
                lslots = [slots]

        self.ABORTED = False
        self.disable_all_buttons(disable=True)
        self.activate_abort_button(activate=True)

        lslots = [int(x) for x in lslots]
        for n in lslots:
            if self.ABORTED:
                self.activate_abort_button(activate=False)
                break
            await self.check_slot(n)
            if stop_at_empty and PRESENT[n] == False:
                break

        self.update_status("READY")
        self.disable_all_buttons(disable=False)


    @work(exclusive=True)
    async def adjust_slot_sequence(self, slots=0):
        try:
            lslots = list(slots)
        except:
            if slots == -1:
                lslots = range(1, 1 + len(robot_get_slots()))
            else:
                lslots = [slots]

        self.ABORTED = False
        self.activate_abort_button(activate=False)
        self.disable_mount_buttons(disable=True)

        self.send_command("GRIPOR_CLOSE\nM400")
        lslots = [int(x) for x in lslots]
        for n in lslots:
            if self.ABORTED:
                self.activate_abort_button(activate=False)
                break
            self.update_status(f"ADJUSTING SLOT {n}")
            self.set_card_busy(n, busy=True)
            await self.send_command_future(adjust_card_in_slot(['adjust', n]), 'adjust')
            self.set_card_busy(n, busy=False)
        self.send_command(move_to_slot(['slot', n]))
        self.send_command("GRIPOR_OPEN")

        self.update_status("READY")
        self.disable_mount_buttons(disable=False)


    def set_card_busy(self, slot, busy=True):
        if slot > 0:
            check_btn = self.query_one(f"#check{slot}")
            if busy:
                check_btn.add_class("busy")
                self.blinker = self.set_interval(0.5, partial(self.busy_animation_cb, check_btn))
                self.blinker.resume()
            else:
                if self.blinker:
                    self.blinker.stop()
                check_btn.remove_class("blunk")
                check_btn.remove_class("busy")

    # temporary mode switch for Mount buttons
    def update_all_mount_buttons(self, mode: str) -> None:
        """
        mode = "mount", normal mount button
        mode = "put", put card in beak in slot
        mode = "disable", all off because unknown card in reader
        """
        global MOUNTED, PRESENT

        if mode == "mount":
            # default mode
            for n in range(1, 1 + len(robot_get_slots())):
                btn.label = "Mount"
                btn.disabled = False
        elif mode == "put":
            # put it back mode but we don't know where
            for n in range(1, 1 + len(robot_get_slots())):
                btn.label = "Put"
                btn.disabled = PRESENT[n]

    def set_card_present(self, slot, present=True):
        global MOUNTED, PRESENT
        PRESENT[slot] = present 
        if slot == 0:
            gfx = self.query_one(f"#sdcard{slot}")
            card_num = self.query_one("#card-number")
            if present:
                gfx.add_class("present")
                gfx.update(self.sdcard_ansi)
                card_num.update(str(MOUNTED).rjust(2))
                card_num.add_class("present")
            else:
                gfx.update(self.sdcard_ansi_disabled)
                gfx.remove_class("present")
                card_num.update("")
                card_num.remove_class("present")
        elif slot > 0:
            check_btn = self.query_one(f"#check{slot}")
            gfx = self.query_one(f"#sdcard{slot}")
            if present:
                check_btn.add_class("present")
                gfx.add_class("present")
                gfx.update(self.sdcard_ansi)
            else:
                check_btn.remove_class("present")
                gfx.remove_class("present")
                gfx.update(self.sdcard_ansi_disabled)

    def disable_mount_buttons(self, disable: bool) -> None:
        for patonki in self.query('.mount-button'):
            patonki.disabled = disable

    def disable_all_buttons(self, disable: bool) -> None:
        for patonki in self.query("Button"):
            patonki.disabled = disable
        self.activate_abort_button(activate=False)

    def activate_abort_button(self, activate: bool) -> None:
        abort = self.query_one("#svc-abort")
        abort.disabled = not activate

    def update_status(self, msg: str) -> None:
        self.log_general.write(msg, LOG_STATUS)
        lable = self.query_one("#svc-status")
        lable.update(msg)
        if msg == "READY":
            lable.remove_class("active")
        else:
            lable.add_class("active")

    def animate_gripor(self, slot, state=GRIPOR_STATE_OPEN) -> None:
        mainrow = self.query_one("#main-buttons-row")
        slotcolumn = mainrow.children[12 - slot]
        x = slotcolumn.region.x - mainrow.region.x + slotcolumn.size.width / 2 - 2

        self.gripor_anim_x = self.gripor_anim_x_end # speedrun current anim
        self.gripor_anim_x_end = x
        self.gripor_anim_state_end = state
        if self.gripor_anim_timer == None:
            self.gripor_anim_timer = self.set_interval(0.2, self.gripor_anim_frame)

    def gripor_anim_frame(self) -> None:
        if self.gripor_anim_x != self.gripor_anim_x_end:
            dx = self.gripor_anim_x_end - self.gripor_anim_x
            if abs(dx) < 1:
                self.gripor_anim_x = self.gripor_anim_x_end
            else:
                dx = ceil(dx / 3) if dx > 0 else floor(dx / 3)
                self.gripor_anim_x += dx
            gripor = self.query_one("#gripor")
            gripor.styles.offset = (self.gripor_anim_x, 0)
            gripor.refresh(layout=True)
        else:
            gripor = self.query_one("#gripor")
            if self.gripor_anim_state_end == GRIPOR_STATE_OPEN:
                gripor.update(Text.from_ansi(ansi_to_truecolor(GRIPOR_OPEN_ANS, THEME_BGCOLOR)))
            else:
                gripor.update(Text.from_ansi(ansi_to_truecolor(GRIPOR_CLOSED_ANS, THEME_BGCOLOR)))

            self.gripor_anim_timer.stop()
            self.gripor_anim_timer = None
            gripor.styles.offset = (self.gripor_anim_x, 0)
            gripor.refresh(layout=True)

    def go_offline(self) -> None:
        # disable controls
        self.disable_all_buttons(disable=True)
        self.close_pipes()

        if self.reopen_timer == None:
            self.reopen_timer = self.set_interval(5.0, self.open_pipes)

    def send_command_future(self, cmd, which):
        self.command_future = asyncio.get_running_loop().create_future()
        self.command_future.which = which
        self.send_command(cmd)
        return self.command_future

    @work(exclusive=True)
    async def mount_slot_sequence(self, slot=0):
        global MOUNTED
        slot = int(slot)
        if MOUNTED != 0 and MOUNTED != slot:
            dismo_instance = self.dismount_slot_sequence()
            await dismo_instance.wait()

        if MOUNTED == slot:
            self.log_general.write("Card already mounted.", LOG_MEDIA)
            return

        self.update_status(f"MOUNTING CARD {slot}")
        self.disable_all_buttons(disable=True)
        try:
            n = slot
            self.set_card_busy(slot, busy=True)
            dismo_btn = self.query_one(f"#dismount")

            self.animate_gripor(slot=n, state=GRIPOR_STATE_CLOSED)
            await self.send_command_future(cmd_get(['get', n]), 'get')
            self.log_general.write(f"ANIMATE GRIPOR TO {n}", LOG_INFO)
            self.animate_gripor(slot=0, state=GRIPOR_STATE_CLOSED)
            self.log_general.write(f"ANIMATE GRIPOR TO {0}", LOG_INFO)
            await self.send_command_future(move_to_slot(['slot', 0]), 'slot')

            self.card_sensor_future = asyncio.get_running_loop().create_future()
            self.send_command("M400\nQUERY_FILAMENT_SENSOR SENSOR=card_sensor")
            await self.card_sensor_future
            if self.card_sensor_future.result():
                self.set_card_present(slot, present=True)
                await self.send_command_future(cmd_put(['put', 0]), 'put')
                self.animate_gripor(slot=0, state=GRIPOR_STATE_OPEN)
                dismo_btn.disabled = False
                dismo_btn.label = f"Dismount"
                MOUNTED = n

                self.set_card_present(0, present=True)
            else:
                self.send_command("GRIPOR_OPEN")
                self.set_card_present(slot, present=False)
                self.animate_gripor(slot=0, state=GRIPOR_STATE_OPEN)
            self.set_card_busy(slot, busy=False)
        finally:
            self.update_status("READY")
            self.disable_all_buttons(disable=False)

    @work(exclusive=True)
    async def dismount_slot_sequence(self):
        global MOUNTED, PRESENT
        if MOUNTED == 0:
            await self.check_slot(0)

            if not PRESENT[0]:
                self.log_general.write(f"No card in reader")
                return

            self.log_general.write(f"Find empty slot for rogue card", LOG_MEDIA)

            #check_slots_instance = self.check_slot_sequence(-1, stop_at_empty=True)
            #await check_slots_instance.wait()

            await self.check_slot_sequence_fuu(-1, stop_at_empty=True)
            for n in range(1, 1 + len(robot_get_slots())):
                if not PRESENT[n]:
                    self.log_general.write(f"Slot {n} was free, new home for rogue card")
                    MOUNTED = n
                    break

            if MOUNTED == 0:
                self.log_general.write(f"No room for card in reader")

        dismo_btn = self.query_one(f"#dismount")
        dismo_btn.text = "Dismount"
        #dismo_btn.disabled = True

        self.disable_all_buttons(disable=True)
        self.update_status(f"DISMOUNTING CARD {MOUNTED}")
        try:
            self.set_card_busy(MOUNTED, busy=True)
            self.animate_gripor(slot=0, state=GRIPOR_STATE_OPEN)
            await self.send_command_future(move_to_slot(['slot', 0]), 'slot')
            self.animate_gripor(slot=0, state=GRIPOR_STATE_CLOSED)
            await self.send_command_future(cmd_get(['get', 0]), which='get')
            self.animate_gripor(slot=MOUNTED, state=GRIPOR_STATE_OPEN)
            await self.send_command_future(cmd_put(['put', MOUNTED]), which='put')
            self.set_card_busy(MOUNTED, busy=False)
            self.set_card_present(MOUNTED)
            MOUNTED = 0
            self.disable_all_buttons(disable=False)
            self.set_card_present(0, present=False)
        finally:
            self.update_status("READY")

    def busy_animation_cb(self, btn):
        #self.log_general.write(f"busy_animation_cb {btn}", LOG_INFO)
        if btn.has_class("blunk"):
            btn.remove_class("blunk")
        else:
            btn.add_class("blunk")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        #self.log_general.write(f"on_button_pressed id={event.button.id}")
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
        if event.button.id == "svc-abort":
            self.update_status("ABORTING")
            self.ABORTED = True
        if event.button.id == "svc-rehome":
            self.rehome()
        if event.button.id == "svc-check-all":
            self.check_slot_sequence(-1)
        if event.button.id == "svc-adj-all":
            self.adjust_slot_sequence(-1)

    async def read_media_dir(self) -> None:
        try:
            files = await asyncio.to_thread(os.listdir, robot_get_mount_point())
            self.query_one(DirectoryTree).reload()
            self.log_general.write(f"[bold cyan]Files:[/bold cyan] {' '.join(files)}", LOG_MEDIA)
        except OSError:
            self.notify("Drive was not ready", severity="error")

def ansi_to_truecolor(ansi_str: str, bg = (0,0,0), sd = (40,40,40), contacts=(170,85,0)) -> str:
    """Converts 4-bit standard ANSI backgrounds and foregrounds to true RGB strings

    so Textual's theme engine cannot override or mutate them.
    """
    # Standard mapping for default 16-color terminals
    
    ansi_map = {
        "30": f"38;2;{sd[0]};{sd[1]};{sd[2]}",      # sdcard colour
        "37": "38;2;170;170;170",  # FG White
        "40": f"48;2;{bg[0]};{bg[1]};{bg[2]}",        # BG Black -> Absolute RGB #000000
        "43": f"48;2;{contacts[0]};{contacts[1]};{contacts[2]}",     # contacts
    }
    
    def replace_code(match):
        codes = match.group(1).split(';')
        new_codes = [ansi_map.get(c, c) for c in codes]
        return f"\x1b[{';'.join(new_codes)}m"

    # Regex captures sequence formatting values inside \x1b[...m
    return re.sub(r'\x1b\[([\d;]+)m', replace_code, ansi_str)


def load_logo():
    global LOGO_W, LOGO_H, LOGO_BMP
    reader = png.Reader(filename="l4a.png")
    LOGO_W, LOGO_H, LOGO_BMP, info = reader.read()

    global SDCARD_ANS
    with open("sdcard.ans", "r") as sdcard:
        SDCARD_ANS = sdcard.read() #hardcode_ansi_to_truecolor(sdcard.read())
    global GRIPOR_OPEN_ANS
    with open("gripor-open.ans", "r") as ans:
        GRIPOR_OPEN_ANS = ans.read()
    global GRIPOR_CLOSED_ANS
    with open("gripor-closed.ans", "r") as ans:
        GRIPOR_CLOSED_ANS = ans.read()
	

if __name__ == "__main__":
    load_logo()
    #exit()
    target_pipe = parse_config_and_args()
    app = TextualRobotnik(pipe_path=target_pipe)
    app.run()
