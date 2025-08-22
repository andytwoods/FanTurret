#!/usr/bin/env python
"""
Fan Turret Control API

This is a Quart-based web application that provides control over a pan-tilt mechanism.
The application exposes several endpoints:

Control Endpoints:
- GET /: Returns a status message indicating the service is running
- GET /control: Starts the automatic control mode with a sine wave pattern and returns
  a stream of Server-Sent Events with position updates
- GET /reset: Resets the pan and tilt positions to 0 and maintains the position for 10 seconds by default
- GET /reset/<duration>: Resets the pan and tilt positions to 0 and maintains the position
  for the specified duration (in seconds)
- GET /set/<pan>/<tilt>: Sets the pan and tilt to specific values (between -90 and 90)
  and maintains the position for 10 seconds by default
- GET /set/<pan>/<tilt>/<duration>: Sets the pan and tilt to specific values and maintains
  the position for the specified duration (in seconds)
- GET /position_control: Serves an HTML page with a visual interface for controlling the pan and tilt
  mechanism using mouse or touch input
- GET /video_feed: Streams video from the webcam as a multipart response with JPEG frames

Diagnostic Endpoints:
- GET /camera_diagnostics: Returns detailed diagnostic information about the camera
- GET /camera_errors: Returns the most recent camera error logs
- GET /reset_camera: Forcibly resets the camera
- GET /configure_camera: Allows manually configuring camera parameters via query parameters:
  - primary_index: The primary camera index to use
  - aggressive_reset: Whether to use aggressive reset (true/false)
  - max_init_attempts: Maximum number of initialization attempts

To run the application:
    python main.py

The server will start on 0.0.0.0:5000
"""

import math
import os
import sys
import time
import asyncio
import cv2
import numpy as np

from quart import Quart, jsonify, render_template, Response, request
from stepper_hat import controller_gpio

# Initialize the webcam variable, but don't open it yet
# We'll open it in the setup function to ensure proper initialization
camera = None

# Camera configuration
CAMERA_CONFIG = {
    'primary_index': 0,     # Default camera index to try first
    'backup_indices': [1, 2, 3],  # Backup camera indices to try if primary fails
    'max_init_attempts': 3,  # Maximum number of initialization attempts
    'init_retry_delay': 2.0,  # Delay between initialization attempts (seconds)
    'aggressive_reset': True,  # Whether to use aggressive reset mechanism
    'error_log_file': 'camera_errors.log'  # File to log camera errors
}

# Initialize error logging
def log_camera_error(error_message):
    """
    Log camera errors to a file for later analysis.

    Args:
        error_message (str): The error message to log
    """
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(CAMERA_CONFIG['error_log_file'], 'a') as f:
            f.write(f"{timestamp} - {error_message}\n")
    except Exception as e:
        print(f"Error writing to log file: {e}")
        # If we can't write to the log file, just print to console
        print(f"CAMERA ERROR: {error_message}")

def initialize_camera(attempt=1, last_error=None):
    """
    Initialize the camera with robust error handling and fallback options.

    This function attempts to initialize the camera using the primary index first,
    then falls back to backup indices if the primary fails. It also includes retry
    logic and detailed error reporting.

    Args:
        attempt (int): Current attempt number (used for recursion)
        last_error (Exception): The last error encountered (used for logging)

    Returns:
        cv2.VideoCapture or None: Initialized camera object or None if all attempts fail
    """
    global camera

    # If we've exceeded the maximum number of attempts, give up
    if attempt > CAMERA_CONFIG['max_init_attempts']:
        error_msg = f"Failed to initialize camera after {attempt-1} attempts. Last error: {last_error}"
        log_camera_error(error_msg)
        print(f"ERROR: {error_msg}")
        return None

    # Determine which camera index to try
    if attempt == 1:
        # First attempt, try the primary index
        camera_index = CAMERA_CONFIG['primary_index']
        print(f"Attempting to initialize camera with primary index {camera_index}...")
    else:
        # Subsequent attempts, try backup indices
        backup_index = attempt - 2  # -2 because attempt starts at 1 and we want to start at index 0
        if backup_index < len(CAMERA_CONFIG['backup_indices']):
            camera_index = CAMERA_CONFIG['backup_indices'][backup_index]
            print(f"Attempting to initialize camera with backup index {camera_index} (attempt {attempt}/{CAMERA_CONFIG['max_init_attempts']})...")
        else:
            # If we've tried all backup indices, retry the primary index
            camera_index = CAMERA_CONFIG['primary_index']
            print(f"Retrying primary camera index {camera_index} (attempt {attempt}/{CAMERA_CONFIG['max_init_attempts']})...")

    try:
        # If aggressive reset is enabled and this is not the first attempt,
        # try to reset the system's camera subsystem
        if CAMERA_CONFIG['aggressive_reset'] and attempt > 1:
            try:
                # On Windows, we can try to release and reinitialize the camera API
                if sys.platform == 'win32':
                    print("Performing aggressive camera reset (Windows)...")
                    # Release all OpenCV windows to free resources
                    cv2.destroyAllWindows()
                    # Force garbage collection to release any lingering resources
                    import gc
                    gc.collect()
                # On Linux, we might try different approaches
                elif sys.platform.startswith('linux'):
                    print("Performing aggressive camera reset (Linux)...")
                    # On Linux, we could potentially use v4l2-ctl to reset the camera
                    # This would require the v4l-utils package to be installed
                    # For now, we'll just do a longer sleep
                    time.sleep(CAMERA_CONFIG['init_retry_delay'] * 2)
            except Exception as e:
                log_camera_error(f"Error during aggressive reset: {e}")
                print(f"WARNING: Error during aggressive reset: {e}")

        # Attempt to initialize the camera
        cam = cv2.VideoCapture(camera_index)

        # Check if the camera was opened successfully
        if cam.isOpened():
            # Get and print camera properties for debugging
            width = cam.get(cv2.CAP_PROP_FRAME_WIDTH)
            height = cam.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fps = cam.get(cv2.CAP_PROP_FPS)
            backend = cam.getBackendName()
            print(f"SUCCESS: Camera initialized with index {camera_index}: {width}x{height} @ {fps}fps (Backend: {backend})")

            # Read a test frame to verify camera is working
            success, frame = cam.read()
            if success and frame is not None:
                print(f"SUCCESS: Test frame read successful from camera index {camera_index}")
                # Log successful initialization
                log_camera_error(f"Camera successfully initialized with index {camera_index}")
                return cam
            else:
                error_msg = f"Camera opened with index {camera_index} but test frame read failed"
                log_camera_error(error_msg)
                print(f"WARNING: {error_msg}")

                # Try to release the camera before trying again
                try:
                    cam.release()
                except Exception as e:
                    error_msg = f"Failed to release camera after failed test frame: {e}"
                    log_camera_error(error_msg)
                    print(f"ERROR: {error_msg}")

                # Wait before trying again
                time.sleep(CAMERA_CONFIG['init_retry_delay'])
                return initialize_camera(attempt + 1, Exception("Test frame read failed"))
        else:
            error_msg = f"Failed to open camera with index {camera_index}"
            log_camera_error(error_msg)
            print(f"WARNING: {error_msg}")

            # Wait before trying again
            time.sleep(CAMERA_CONFIG['init_retry_delay'])
            return initialize_camera(attempt + 1, Exception(error_msg))

    except Exception as e:
        error_msg = f"Exception during camera initialization with index {camera_index}: {e}"
        log_camera_error(error_msg)
        print(f"ERROR: {error_msg}")

        # Wait before trying again
        time.sleep(CAMERA_CONFIG['init_retry_delay'])
        return initialize_camera(attempt + 1, e)

def get_available_cameras(max_to_check=10):
    """
    Detect available cameras on the system.

    This function attempts to open each camera index from 0 to max_to_check-1
    and returns a list of indices that were successfully opened.

    Args:
        max_to_check (int): Maximum number of camera indices to check

    Returns:
        list: List of available camera indices
    """
    available_cameras = []

    print("Scanning for available cameras...")
    for i in range(max_to_check):
        try:
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                # Try to read a frame to confirm it's working
                success, _ = cap.read()
                if success:
                    available_cameras.append(i)
                    print(f"Found working camera at index {i}")
                    break
                else:
                    print(f"Camera at index {i} opened but frame read failed")
                cap.release()
            else:
                print(f"No camera found at index {i}")
        except Exception as e:
            print(f"Error checking camera at index {i}: {e}")

    if available_cameras:
        print(f"Found {len(available_cameras)} available cameras: {available_cameras}")
    else:
        print("No available cameras found!")

    return available_cameras

app = Quart(__name__)

@app.route('/')
async def index():
    """
    Root endpoint that returns a simple status message.

    Returns:
        JSON: A simple status message indicating the service is running.
    """
    return jsonify({"status": "Fan Turret is running"})

@app.route('/control')
async def control():
    """
    Starts the automatic control mode with a sine wave pattern.

    This endpoint returns a stream of Server-Sent Events (SSE) with position updates.
    The pan and tilt mechanism will move in a sine wave pattern, with both pan and tilt
    angles following the same pattern. Updates are sent to the client approximately
    every 100 iterations (about every 0.5 seconds).

    Returns:
        Response: A streaming response with Server-Sent Events containing position updates.
    """
    async def generate():
        count = 0
        while True:
            # Get the time in seconds
            t = time.time()

            # Generate an angle using a sine wave (-1 to 1) multiplied by 90 (-90 to 90)
            a = math.sin(t * 2) * 90

            # Cast a to int for v0.0.2
            a = int(a)

            controller_gpio.pan(a)
            controller_gpio.tilt(a)

            # Two decimal places is quite enough!
            angle = round(a, 2)
            print(angle)

            # Send an update every 100 iterations
            count += 1
            if count >= 100:
                yield f"data: {{\"angle\": {angle}}}\n\n"
                count = 0

            # Sleep for a bit so we're not hammering the HAT with updates
            await asyncio.sleep(0.005)

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route('/reset')
@app.route('/reset/<int:duration>')
async def reset(duration=10):
    """
    Resets the pan and tilt positions to 0 and maintains the position.

    This endpoint sets both the pan and tilt angles to 0, which is the center position.
    The position is maintained by continuously sending signals to the servos for the specified
    duration (in seconds).

    Args:
        duration (int, optional): How long to maintain the position in seconds. Defaults to 10.

    Returns:
        Response: A streaming response with Server-Sent Events containing position updates,
                 or a JSON response if duration is 0.
    """
    # If duration is 0, just set the position once and return
    if duration <= 0:
        controller_gpio.tilt(0)
        controller_gpio.pan(0)
        return jsonify({"status": "Pan and tilt reset to 0 (one-time)"})

    async def generate():
        count = 0
        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            # Continuously send the reset position commands
            controller_gpio.pan(0)
            controller_gpio.tilt(0)

            # Send an update every 100 iterations
            count += 1
            if count >= 100:
                yield f"data: {{\"pan\": 0, \"tilt\": 0, \"remaining\": {round(end_time - time.time(), 1)}}}\n\n"
                count = 0

            # Sleep for a bit so we're not hammering the HAT with updates
            await asyncio.sleep(0.005)

        # Send a final update
        yield f"data: {{\"pan\": 0, \"tilt\": 0, \"remaining\": 0, \"status\": \"complete\"}}\n\n"

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route('/set/<int:pan>/<int:tilt>')
@app.route('/set/<int:pan>/<int:tilt>/<int:duration>')
async def set_position(pan, tilt, duration=10):
    """
    Sets the pan and tilt to specific values and maintains the position.

    This endpoint allows manual control of the pan and tilt mechanism by setting
    specific angles for both axes. Values are clamped to the valid range of -90 to 90 degrees.
    The position is maintained by continuously sending signals to the servos for the specified
    duration (in seconds).

    Args:
        pan (int): The pan angle in degrees (-90 to 90).
        tilt (int): The tilt angle in degrees (-90 to 90).
        duration (int, optional): How long to maintain the position in seconds. Defaults to 10.

    Returns:
        Response: A streaming response with Server-Sent Events containing position updates,
                 or a JSON response if duration is 0.
    """
    pan = 1000 - pan
    tilt = 1000 - tilt
    # Ensure values are within the valid range (-90 to 90)
    pan = max(-90, min(90, pan))
    tilt = max(-90, min(90, tilt))

    # If duration is 0, just set the position once and return
    if duration <= 0:
        controller_gpio.pan(pan)
        controller_gpio.tilt(tilt)

        return jsonify({
            "status": "Position set (one-time)",
            "pan": pan,
            "tilt": tilt
        })

    async def generate():
        count = 0
        start_time = time.time()
        end_time = start_time + duration

        while time.time() < end_time:
            # Continuously send the same position commands to maintain the position
            controller_gpio.pan(pan)
            controller_gpio.tilt(tilt)

            # Send an update every 100 iterations
            count += 1
            if count >= 100:
                yield f"data: {{\"pan\": {pan}, \"tilt\": {tilt}, \"remaining\": {round(end_time - time.time(), 1)}}}\n\n"
                count = 0

            # Sleep for a bit so we're not hammering the HAT with updates
            await asyncio.sleep(0.005)

        # Send a final update
        yield f"data: {{\"pan\": {pan}, \"tilt\": {tilt}, \"remaining\": 0, \"status\": \"complete\"}}\n\n"

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route('/position_control')
async def position_control():
    """
    Serves an HTML page that allows controlling the pan and tilt mechanism using mouse or touch.

    This endpoint returns an HTML page with a square interface where the user can move an element
    using either a mouse or their finger. The element's position within the square is converted
    to pan and tilt values and sent to the /set/<pan>/<tilt> endpoint.

    Returns:
        HTML: An HTML page with the control interface.
    """
    return await render_template('position_control.html')

@app.route('/camera_diagnostics')
async def camera_diagnostics():
    """
    Provides detailed diagnostic information about the camera.

    This endpoint returns a JSON object with information about:
    - Available cameras on the system
    - Current camera configuration
    - Current camera status and properties
    - Last error encountered

    This can be used to troubleshoot camera issues without streaming video.

    Returns:
        JSON: Detailed diagnostic information about the camera.
    """
    global camera

    # Get available cameras
    available_cameras = get_available_cameras(max_to_check=10)

    # Check current camera status
    camera_status = "Not initialized"
    camera_properties = {}
    last_frame_status = "Unknown"

    if camera is not None:
        if camera.isOpened():
            camera_status = "Initialized and opened"

            # Get camera properties
            properties = {
                "width": camera.get(cv2.CAP_PROP_FRAME_WIDTH),
                "height": camera.get(cv2.CAP_PROP_FRAME_HEIGHT),
                "fps": camera.get(cv2.CAP_PROP_FPS),
                "brightness": camera.get(cv2.CAP_PROP_BRIGHTNESS),
                "contrast": camera.get(cv2.CAP_PROP_CONTRAST),
                "saturation": camera.get(cv2.CAP_PROP_SATURATION),
                "hue": camera.get(cv2.CAP_PROP_HUE),
                "gain": camera.get(cv2.CAP_PROP_GAIN),
                "exposure": camera.get(cv2.CAP_PROP_EXPOSURE),
                "backend": camera.getBackendName()
            }
            camera_properties = {k: float(v) for k, v in properties.items() if v is not None}

            # Try to read a test frame
            success, _ = camera.read()
            if success:
                last_frame_status = "Success"
            else:
                last_frame_status = "Failed"
        else:
            camera_status = "Initialized but not opened"

    # Prepare diagnostic information
    diagnostic_info = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "available_cameras": available_cameras,
        "camera_config": CAMERA_CONFIG,
        "camera_status": camera_status,
        "camera_properties": camera_properties,
        "last_frame_status": last_frame_status,
        "opencv_version": cv2.__version__,
        "system_info": {
            "platform": sys.platform,
            "python_version": sys.version
        }
    }

    return jsonify(diagnostic_info)

@app.route('/camera_errors')
async def camera_errors():
    """
    Returns the most recent camera error logs.

    This endpoint reads the camera error log file and returns the most recent entries.
    This can be used to troubleshoot camera issues without having to access the log file directly.

    Returns:
        JSON: Recent camera error logs.
    """
    try:
        # Check if the log file exists
        if not os.path.exists(CAMERA_CONFIG['error_log_file']):
            return jsonify({
                "status": "warning",
                "message": "No camera error log file found",
                "errors": []
            })

        # Read the last 50 lines from the log file
        with open(CAMERA_CONFIG['error_log_file'], 'r') as f:
            # Read all lines and get the last 50
            lines = f.readlines()
            recent_errors = lines[-50:] if len(lines) > 50 else lines

            # Clean up the lines (remove newlines, etc.)
            recent_errors = [line.strip() for line in recent_errors]

        return jsonify({
            "status": "success",
            "message": f"Retrieved {len(recent_errors)} recent camera errors",
            "errors": recent_errors
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error reading camera error log: {e}",
            "errors": []
        })

@app.route('/configure_camera')
async def configure_camera():
    """
    Allows manually configuring camera parameters.

    This endpoint accepts query parameters to update the camera configuration:
    - primary_index: The primary camera index to use
    - aggressive_reset: Whether to use aggressive reset (true/false)
    - max_init_attempts: Maximum number of initialization attempts

    Returns:
        JSON: Updated camera configuration.
    """
    # Get query parameters
    primary_index = request.args.get('primary_index', type=int)
    aggressive_reset = request.args.get('aggressive_reset')
    max_init_attempts = request.args.get('max_init_attempts', type=int)

    # Update configuration if parameters are provided
    if primary_index is not None:
        CAMERA_CONFIG['primary_index'] = primary_index
        log_camera_error(f"Camera primary_index manually set to {primary_index}")

    if aggressive_reset is not None:
        CAMERA_CONFIG['aggressive_reset'] = aggressive_reset.lower() == 'true'
        log_camera_error(f"Camera aggressive_reset manually set to {CAMERA_CONFIG['aggressive_reset']}")

    if max_init_attempts is not None:
        CAMERA_CONFIG['max_init_attempts'] = max_init_attempts
        log_camera_error(f"Camera max_init_attempts manually set to {max_init_attempts}")

    # Return the current configuration
    return jsonify({
        "status": "success",
        "message": "Camera configuration updated",
        "config": CAMERA_CONFIG
    })

@app.route('/reset_camera')
async def reset_camera():
    """
    Forcibly resets the camera.

    This endpoint releases the current camera (if any) and attempts to reinitialize it
    using the robust initialization mechanism. This can be used to recover from camera
    issues without restarting the application.

    Returns:
        JSON: Status of the camera reset operation.
    """
    global camera

    # Release the current camera if it exists
    if camera is not None:
        try:
            print("Forcibly releasing camera...")
            camera.release()
        except Exception as e:
            print(f"Error releasing camera: {e}")

    # Set camera to None to ensure clean state
    camera = None

    # Wait a moment to ensure resources are freed
    await asyncio.sleep(1)

    # Reinitialize the camera
    print("Forcibly reinitializing camera...")
    camera = initialize_camera()

    if camera is not None and camera.isOpened():
        # Try to read a test frame
        success, _ = camera.read()
        if success:
            return jsonify({
                "status": "success",
                "message": "Camera successfully reset and test frame read"
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "Camera reset succeeded but test frame read failed"
            })
    else:
        return jsonify({
            "status": "error",
            "message": "Failed to reset camera"
        })

@app.route('/video_feed')
async def video_feed():
    """
    Streams video from the webcam.

    This endpoint returns a multipart response with JPEG frames from the webcam.
    The video stream can be embedded in HTML img tags or used as a background.

    Returns:
        Response: A streaming response with JPEG frames from the webcam.
    """
    global camera

    # Create a fallback frame for when camera is unavailable
    fallback_frame = np.zeros((480, 640, 3), dtype=np.uint8)  # Black frame
    cv2.putText(fallback_frame, "Camera Unavailable", (120, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, fallback_buffer = cv2.imencode('.jpg', fallback_frame)
    fallback_bytes = fallback_buffer.tobytes()

    # Create a heartbeat frame to keep the connection alive
    heartbeat_frame = np.zeros((8, 8, 3), dtype=np.uint8)  # Tiny black frame for heartbeat
    _, heartbeat_buffer = cv2.imencode('.jpg', heartbeat_frame, [cv2.IMWRITE_JPEG_QUALITY, 30])
    heartbeat_bytes = heartbeat_buffer.tobytes()

    # Configuration parameters
    MAX_FAILURES = 5  # Maximum consecutive failures before resetting camera
    MIN_FRAME_INTERVAL = 0.1  # Minimum time between frames (10 FPS max)
    MAX_FRAME_INTERVAL = 0.5  # Maximum time between frames (2 FPS min)
    HEARTBEAT_INTERVAL = 2.0  # Send a heartbeat every 2 seconds if no frames

    # Initialize tracking variables
    consecutive_failures = 0
    last_frame_time = 0
    last_heartbeat_time = 0
    current_interval = MIN_FRAME_INTERVAL

    # Check if camera is None (not initialized) and try to initialize it
    if camera is None:
        print("Camera not initialized, attempting to initialize now...")
        # Use the robust initialization function
        camera = initialize_camera()
        if camera is None:
            print("Failed to initialize camera on demand using all available methods")
            # We'll continue with the fallback frame

    async def generate():
        nonlocal consecutive_failures, last_frame_time, last_heartbeat_time, current_interval
        global camera

        # Set initial timestamps
        last_frame_time = time.time()
        last_heartbeat_time = time.time()

        while True:
            try:
                current_time = time.time()

                # Check if it's time to send a heartbeat to keep the connection alive
                if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    print(f"Sending heartbeat to keep connection alive")
                    last_heartbeat_time = current_time
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + heartbeat_bytes + b'\r\n')

                # Check if enough time has passed to send a new frame
                if current_time - last_frame_time < current_interval:
                    # Not time for a new frame yet, sleep a bit and continue
                    await asyncio.sleep(0.01)  # Short sleep to prevent CPU spinning
                    continue

                # Update last frame time
                last_frame_time = current_time

                # Check if camera is None or not opened
                if camera is None or not camera.isOpened():
                    print(f"Camera not available, attempting to initialize/reopen...")

                    # If camera exists, try to release it first
                    if camera is not None:
                        try:
                            camera.release()
                        except Exception as e:
                            print(f"Error releasing camera: {e}")

                    # Set camera to None to ensure clean state
                    camera = None

                    # Wait before reopening
                    await asyncio.sleep(1)

                    # Try to initialize/reopen the camera using the robust initialization function
                    print("Attempting to reinitialize camera...")
                    camera = initialize_camera()

                    if camera is not None and camera.isOpened():
                        print("Successfully reinitialized camera")
                        # Reset failure counter on successful initialization
                        consecutive_failures = 0
                        # Reset frame interval to default
                        current_interval = MIN_FRAME_INTERVAL
                    else:
                        print("Failed to reinitialize camera using all available methods")
                        camera = None

                    # Use fallback frame regardless of initialization result
                    # This ensures the stream continues even if camera init failed
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')
                    continue

                # Try to read a frame with timeout protection
                frame = None
                success = False

                try:
                    # Read frame from camera
                    success, frame = camera.read()

                    if not success or frame is None:
                        consecutive_failures += 1
                        print(f"Failed to read frame: {consecutive_failures}/{MAX_FAILURES}")

                        # Increase frame interval to reduce load on system
                        current_interval = min(current_interval * 1.5, MAX_FRAME_INTERVAL)
                        print(f"Increasing frame interval to {current_interval:.2f}s")

                        if consecutive_failures >= MAX_FAILURES:
                            print("Too many consecutive failures, attempting to reset camera...")

                            # Try to release the camera
                            try:
                                if camera is not None:
                                    camera.release()
                                    camera = None
                            except Exception as e:
                                print(f"Error releasing camera during reset: {e}")
                                camera = None

                            await asyncio.sleep(1)

                            # Try to reinitialize the camera using the robust initialization function
                            print("Attempting to reinitialize camera after consecutive failures...")
                            camera = initialize_camera()

                            if camera is not None and camera.isOpened():
                                print("Successfully reset camera")
                                # Read a test frame to verify camera is working
                                test_success, _ = camera.read()
                                if test_success:
                                    print("Camera reset confirmed with successful frame read")
                                else:
                                    print("Camera reset succeeded but test frame read failed")
                                    # If test frame read fails, try to release and reinitialize again
                                    try:
                                        camera.release()
                                    except Exception as e:
                                        print(f"Error releasing camera after failed test frame: {e}")
                                    camera = None
                            else:
                                print("Failed to reset camera using all available methods")
                                camera = None

                            # Reset failure counter after reset attempt
                            consecutive_failures = 0

                        # Use fallback frame when frame read fails
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')
                        continue

                    # Reset failure counter and adjust frame interval on success
                    if consecutive_failures > 0:
                        print(f"Successfully read frame after {consecutive_failures} failures")
                        consecutive_failures = 0

                    # Gradually decrease frame interval on success (increase FPS)
                    if current_interval > MIN_FRAME_INTERVAL:
                        current_interval = max(current_interval * 0.9, MIN_FRAME_INTERVAL)

                    # Encode the frame as JPEG
                    try:
                        # Determine quality based on current performance
                        quality = 70  # Default quality
                        if current_interval > MIN_FRAME_INTERVAL * 2:
                            # If we're struggling, reduce quality
                            quality = 50

                        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
                        if not ret:
                            print("Failed to encode frame")
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')
                        else:
                            frame_bytes = buffer.tobytes()

                            # Update heartbeat time when sending a real frame
                            last_heartbeat_time = time.time()

                            # Yield the frame in the multipart response format
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    except Exception as e:
                        print(f"Error encoding frame: {e}")
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')

                except Exception as e:
                    print(f"Error during frame capture: {e}")
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')

                    # Increase frame interval to reduce load
                    current_interval = min(current_interval * 1.5, MAX_FRAME_INTERVAL)

                # Explicitly delete frame to help with memory management
                if frame is not None:
                    del frame

            except Exception as e:
                print(f"Critical error in video stream: {e}")
                # Use fallback frame for any unhandled exceptions
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + fallback_bytes + b'\r\n')

                # Sleep longer after errors to give system time to recover
                await asyncio.sleep(0.5)

    # Set response headers to help prevent the ERR_INCOMPLETE_CHUNKED_ENCODING error
    headers = {
        'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
        'Connection': 'close',  # This can help with some chunked encoding issues
    }

    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers=headers
    )

# Setup and cleanup functions for proper resource management
@app.before_serving
async def setup():
    global camera
    print("Starting Fan Turret application...")

    # Scan for available cameras first
    available_cameras = get_available_cameras()

    # Update the camera configuration based on available cameras
    if available_cameras:
        CAMERA_CONFIG['primary_index'] = available_cameras[0]
        CAMERA_CONFIG['backup_indices'] = available_cameras[1:] if len(available_cameras) > 1 else []
        print(f"Updated camera configuration: primary={CAMERA_CONFIG['primary_index']}, backups={CAMERA_CONFIG['backup_indices']}")
    else:
        print("WARNING: No cameras detected during startup scan. Will try default indices during initialization.")

    # Initialize the webcam using the robust initialization function
    print("Initializing camera...")
    camera = initialize_camera()

    if camera is None:
        print("WARNING: Failed to initialize camera during startup. Will try again when needed.")
    else:
        print("Camera successfully initialized during startup.")

@app.after_serving
async def cleanup():
    global camera
    print("Shutting down Fan Turret application...")

    # Release the camera if it exists and is open
    try:
        if camera is not None and camera.isOpened():
            print("Releasing camera resources...")
            camera.release()
            print("Camera released successfully")
    except Exception as e:
        print(f"Error releasing camera: {e}")

    # Set camera to None to ensure it's properly garbage collected
    camera = None

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


