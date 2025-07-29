# Fan Turret Control Application

This is a Quart-based web application that provides control over a pan-tilt mechanism for a fan turret.

## Features

- Automatic control mode with a sine wave pattern
- Manual control via direct position setting
- Visual interface for controlling the pan and tilt using mouse or touch input
- Continuous position maintenance to ensure servos hold their position

## Installation

1. Clone this repository
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

1. Start the application:

```bash
python main.py
```

2. The server will start on 0.0.0.0:5000
3. Access the application in your web browser:
   - `http://<your-ip>:5000` - Main status page
   - `http://<your-ip>:5000/control` - Automatic control mode
   - `http://<your-ip>:5000/position_control` - Visual control interface

## API Endpoints

- `GET /`: Returns a status message indicating the service is running
- `GET /control`: Starts the automatic control mode with a sine wave pattern and returns a stream of Server-Sent Events with position updates
- `GET /reset`: Resets the pan and tilt positions to 0 and maintains the position for 10 seconds by default
- `GET /reset/<duration>`: Resets the pan and tilt positions to 0 and maintains the position for the specified duration (in seconds)
- `GET /set/<pan>/<tilt>`: Sets the pan and tilt to specific values (between -90 and 90) and maintains the position for 10 seconds by default
- `GET /set/<pan>/<tilt>/<duration>`: Sets the pan and tilt to specific values and maintains the position for the specified duration (in seconds)
- `GET /position_control`: Serves an HTML page with a visual interface for controlling the pan and tilt mechanism using mouse or touch input

## Finding Your Raspberry Pi's IP Address

To access the web interface, you need to know the IP address of your Raspberry Pi. Here are several methods to find it:

### Method 1: Using the Terminal on the Raspberry Pi

```bash
hostname -I
```

This will display all IP addresses assigned to the Pi. The first one is typically the main IP address.

### Method 2: Using Your Router

1. Log into your router's admin interface (typically http://192.168.0.1 or http://192.168.1.1)
2. Look for "Connected Devices" or "DHCP Clients" section
3. Find the device named "raspberry" or "raspberrypi" in the list

### Method 3: Using avahi/Bonjour

If your Raspberry Pi has avahi-daemon running (installed by default on Raspberry Pi OS), you can access it using:

```
raspberrypi.local
```

So your application would be available at `http://raspberrypi.local:5000`

## Debugging the Visual Control Interface

The visual control interface now includes debugging features to help diagnose issues with the pan and tilt values:

1. Visual indicators:
   - A small black dot marks the center of the control area
   - Horizontal and vertical lines show the center axes
   - Red lines mark the boundaries of the control area

2. Debug information:
   - A debug panel shows real-time information about position calculations
   - Raw values and computed pan/tilt values are displayed
   - Error messages are shown if any occur

3. Range checking:
   - Pan and tilt values are explicitly checked to ensure they stay within -90 to 90 degrees
   - The full range of motion should be available in all browsers and devices

4. URL parameter encoding:
   - Negative values in pan/tilt parameters are properly URL-encoded
   - This prevents errors when sending negative values to the server
   - Fixed the "Unexpected token '<', '<!doctype '... is not valid JSON" error

If you're experiencing issues with the range of values (e.g., only getting 0 to 90 instead of -90 to 90), the debug information should help identify the cause. The latest update fixes an issue where negative pan/tilt values would cause an error due to improper URL encoding.

## License

This project is licensed under the MIT License - see the LICENSE file for details.