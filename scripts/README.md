## Environment setup stuff

### klipper & klippy

sudo apt install git python3-virtualenv python3-dev libffi-dev build-essential libncurses-dev gawk -y
git clone https://github.com/Klipper3d/klipper.git
virtualenv -p python3 ~/klippy-env
~/klippy-env/bin/pip install -r ~/library_for_ants/klipper/scripts/klippy-requirements.txt

### /etc/systemd/system/klipper.service

```
#Systemd service file for klipper
[Unit]
Description=Starts klipper on startup
After=network.target

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=svo
RemainAfterExit=yes
ExecStart=/home/svo/klippy-env/bin/python /home/svo/library_for_ants/klipper/klippy/klippy.py /home/svo/library_for_ants/scripts/printer.cfg -l /tmp/klippy.log
Restart=always
RestartSec=10
```

```
sudo systemctl daemon-reload
sudo systemctl enable klipper.service
sudo systemctl start klipper.service
```

### Automount

I had very rough experience across Armbian and Debian. This seems to work on both:
```
sudo cp mnt-robot_media.* /etc/systemd/system/
sudo cp robot-media-watch.timer /etc/systemd/system/
sudo cp robot-media-watch.service /etc/systemd/system/
chmod +x robot-media-check.sh
mkdir /mnt/robot_media
systemctl daemon-reload 
systemctl enable --now mnt-robot_media.automount
systemctl enable --now robot-media-watch.timer
```

### udev hotplug 

Avoid annoying device name changes etc

```
sudo cp 99-klipper-hotplug.rules 99-usb-serial.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

### pythong

pip3 install -r requirements.txt


## References

Kinematics: midTbot

 https://www.buildlog.net/blog/2017/10/the-midtbot-a-new-flavor-of-h-bot/
 https://github.com/bdring/midTbot_esp32



