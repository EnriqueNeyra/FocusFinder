# FocusFinder — A Productivity Tracking Tool, Implementing a Transparent OLED + Pi Camera Module, and Powered by Python OpenCV + Raspberry Pi
Test

The **FocusFinder** is a small desktop productivity tracker/timer that uses a Transparent OLED with a Pi camera module hidden behind it. The FocusFinder uses Python OpenCV to track focus through face detection. 
The timer will count up if you are focused on the screen/monitor in front of you. Spend too much time looking away, and the timer will reset!

<img width="1633" height="999" alt="image" src="https://github.com/user-attachments/assets/f6f684d5-3cc5-4730-a2d7-3b7bf26ac90d" />

---

## Contents

- [Required Hardware](#required-hardware)
- [Pi Setup](#pi-setup)
- [Assembly](#assembly)
- [Using the FocusFinder](#using-the-frame)

---

## Required Hardware

| Item | Link |
|------|------|
| Raspberry Pi Zero 2 W | [Amazon](https://amzn.to/3YBvaBV) |
| Pi Power Supply | [Amazon](https://amzn.to/42dMak0) |
| Waveshare 1.54" Transparent OLED  | [Amazon](https://amzn.to/4jjJQNH) |
| Pi Camera Module V2.1  | [Amazon](https://amzn.to/4keIu8i) |
| Micro SD Card (for Pi OS image) | [Amazon](https://amzn.to/3Z0md5n) |
| Enclosure 3D Print Files | [Printables](https://www.printables.com/model/1287334-eink-picture-frame) |

<p align="center"><img src="https://github.com/user-attachments/assets/17d8eb2a-0daf-4b2d-9818-d128d05cf1a2" width="700"></p>

---

## Pi Setup

**Before starting**, ensure that your Pi is running Raspberry Pi OS (Bookworm) and is connected to your home network.
If you need help installing Raspberry Pi OS, follow the [official guide](https://www.raspberrypi.com/documentation/computers/getting-started.html#installing-the-operating-system).

Once your Pi has booted, open Command Prompt (Windows) or Terminal (Mac), and SSH into the Pi:

```bash
ssh pi@pi.local
```

Then run the following to clone the project and begin setup:

```bash
git clone https://github.com/EnriqueNeyra/FocusFinder.git
cd FocusFinder
sudo bash setup.sh
```

Be sure to **reboot** the Pi after the setup script completes.

---

## Assembly

### 1. Attach the Pi Camera Module to the Pi Zero 2W
<p align="center"><img src="https://github.com/user-attachments/assets/932353ec-4a00-4396-a531-db8d7ce37923" width="700"></p>

### 2. Wire the OLED Display + Driver Board to the Appropriate Pi Pin Headers
<p align="center"><img src="https://github.com/user-attachments/assets/b51d8fce-9536-4238-be88-17283b0e1948" width="700"></p>

### 3. Insert the Pi Into the Base of the Enclosure
<p align="center"><img src="https://github.com/user-attachments/assets/c7d38f4a-1e7d-4249-9dbf-10f76a347c93" width="700"></p>

### 4. Place the Driver Board into the Rear Slot and Tuck Wires
<p align="center"><img src="https://github.com/user-attachments/assets/8d90bb13-36ea-4bee-9e2f-e6ddf2cadc6f" width="700"></p>

### 5. Slot Display into Display/Camera Holder
<p align="center"><img src="https://github.com/user-attachments/assets/dad7fada-553c-40b0-be0d-0e0b53b0061e" width="700"></p>

### 6. Slot Camera into Display/Camera Holder
<p align="center"><img src="https://github.com/user-attachments/assets/6631f0ee-7342-4e55-a98b-9eba4c7aa4fb" width="700"></p>

### 7. Secure Display/Camera Holder to Base and Attach Enclosure Cover
<p align="center"><img src="https://github.com/user-attachments/assets/4097dedf-6115-4c59-a6fe-8280504380c3" width="700"></p>
<p align="center"><img src="https://github.com/user-attachments/assets/19f7288c-768e-4e1c-ac34-68a47e7dc2f9" width="700"></p>

### Assembly is now complete!
<p align="center"><img src="https://github.com/user-attachments/assets/f6f684d5-3cc5-4730-a2d7-3b7bf26ac90d" width="700"></p>

---

## Using the FocusFinder

Connect the power cable to the Pi. Place it on a flat surface on your desk, directly in front of you. Angle the display so that it is aimed squarely at your face, and ensure that there is sufficient lighting on your face. Poor lighting will prevent your face from being detected.
From the initial state (00:00), you must be 'focused' and looking in front of you for ~3 seconds before the timer will begin counting. When 'unfocused' and looking away, there is a grace period of ~10 seconds before the timer will reset.
