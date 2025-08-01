# FanTurret

A web-based control system for a pan-tilt mechanism with camera integration. This project allows you to control a fan or camera mounted on a pan-tilt platform through an intuitive web interface.

## Features

- Web-based control interface for pan and tilt movements
- Live video streaming from attached camera
- Manual control via mouse/touch interface
- Auto-tracking of faces and hands using MediaPipe
- Adjustable video quality settings
- Fullscreen mode for better control
- REST API for programmatic control

## Software Demo

Below is a demonstration of the software interface in action:

![Software Demo](readme_media/software.gif)

## Hardware Demo

Below is a demonstration of the hardware in action:

![Hardware Demo](readme_media/hardware.gif)

## Installation

### Prerequisites

- Python 3.11+
- Raspberry Pi (or similar) with pan-tilt HAT
- Web camera

### Setup

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/FanTurret.git
   cd FanTurret
   ```

2. Install required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Connect your pan-tilt hardware and camera

## Usage

1. Start the application:
   ```
   python main.py
   ```

2. Open a web browser and navigate to:
   ```
   http://localhost:5000
   ```

3. Use the interface to control the pan-tilt mechanism:
   - Click or drag within the control area to position the device
   - Use the quality controls to adjust video settings
   - Enable fullscreen mode for a better experience

## API Endpoints

- `/` - Main page
- `/control` - Control interface
- `/position_control` - Position control interface
- `/set/<pan>/<tilt>/<duration>` - Set pan and tilt position
- `/reset/<duration>` - Reset to center position
- `/video_feed` - Camera video stream
- `/camera_diagnostics` - Camera diagnostic information