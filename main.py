#!/usr/bin/env python
"""
Fan Turret Control API

This is a Quart-based web application that provides control over a pan-tilt mechanism.
The application exposes several endpoints:

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

To run the application:
    python main.py

The server will start on 0.0.0.0:5000
"""

import math
import time
import asyncio

from quart import Quart, jsonify, render_template
import pantilthat

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

            pantilthat.pan(a)
            pantilthat.tilt(a)

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
        pantilthat.tilt(0)
        pantilthat.pan(0)
        return jsonify({"status": "Pan and tilt reset to 0 (one-time)"})
    
    async def generate():
        count = 0
        start_time = time.time()
        end_time = start_time + duration
        
        while time.time() < end_time:
            # Continuously send the reset position commands
            pantilthat.pan(0)
            pantilthat.tilt(0)
            
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
        pantilthat.pan(pan)
        pantilthat.tilt(tilt)
        
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
            pantilthat.pan(pan)
            pantilthat.tilt(tilt)
            
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
    
