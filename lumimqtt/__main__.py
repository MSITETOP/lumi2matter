"""
Matter Bridge entry point for Lumi Gateway using CircuitMatter
Run with: python3 -m lumimqtt
"""

import asyncio as aio
import json
import logging
import os
import sys
from pathlib import Path

try:
    import circuitmatter as cm
    from circuitmatter.device_types.lighting import extended_color
except ImportError:
    print("ERROR: CircuitMatter not installed!")
    print("Please install: pip3 install circuitmatter")
    sys.exit(1)

from .light import Light
from .button import Button
from .platform import devices

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LumiRGBLight(extended_color.ExtendedColorLight):
    """CircuitMatter adapter for Lumi RGB Light"""
    
    def __init__(self, name: str, lumi_light: Light):
        super().__init__(name)
        self._light = lumi_light
        self._brightness = 1.0  # 0.0 to 1.0
        self._is_on = True
        
        # Read current state from hardware
        if self._light.state['state'] == 'ON':
            self._is_on = True
            self._brightness = self._light.state['brightness'] / 255.0
        else:
            self._is_on = False
    
    @property
    def color_rgb(self):
        """Return current RGB color as 24-bit integer (0xRRGGBB)"""
        color = self._light.state['color']
        rgb_value = (color['r'] << 16) | (color['g'] << 8) | color['b']
        return rgb_value
    
    @color_rgb.setter
    def color_rgb(self, value: int):
        """Set RGB color from 24-bit integer (0xRRGGBB)"""
        r = (value >> 16) & 0xFF
        g = (value >> 8) & 0xFF
        b = value & 0xFF
        
        logger.info(f"Setting color to RGB({r}, {g}, {b})")
        
        # Update light asynchronously
        aio.create_task(self._light.set({
            'color': {'r': r, 'g': g, 'b': b}
        }, 0))
    
    @property
    def brightness(self):
        """Return brightness 0.0 to 1.0"""
        return self._brightness
    
    @brightness.setter  
    def brightness(self, value: float):
        """Set brightness 0.0 to 1.0"""
        self._brightness = max(0.0, min(1.0, value))
        brightness_255 = int(self._brightness * 255)
        
        logger.info(f"Setting brightness to {brightness_255}/255")
        
        # Update light asynchronously
        aio.create_task(self._light.set({
            'brightness': brightness_255
        }, 0))
    
    def on(self):
        """Turn light on"""
        logger.info("Turning light ON")
        self._is_on = True
        aio.create_task(self._light.set({'state': 'ON'}, 0))
    
    def off(self):
        """Turn light off"""
        logger.info("Turning light OFF")
        self._is_on = False
        aio.create_task(self._light.set({'state': 'OFF'}, 0))


def load_config():
    """Load configuration from JSON file"""
    config_path = os.environ.get(
        'LUMIMQTT_CONFIG',
        '/etc/lumimqtt.json'
    )
    
    if not os.path.exists(config_path):
        logger.warning(f"Config file not found: {config_path}")
        logger.info("Using default configuration")
        return {
            'device_id': 'lumi_gateway',
            'device_name': 'Lumi Gateway',
            'binary_sensors': {},
            'custom_commands': {},
        }
    
    with open(config_path, 'r') as f:
        return json.load(f)


def main():
    """Main entry point for CircuitMatter"""
    logger.info("Starting Lumi Matter Bridge with CircuitMatter")
    
    # Load configuration
    config = load_config()
    device_name = config.get('device_name', 'Lumi Gateway')
    
    # Create CircuitMatter instance
    matter = cm.CircuitMatter()
    
    logger.info("Discovering Lumi devices...")
    
    # Get devices from platform
    binary_sensors = config.get('binary_sensors', {})
    custom_commands = config.get('custom_commands', {})
    
    lumi_devices = list(devices(binary_sensors, custom_commands))
    
    # Register devices with CircuitMatter
    device_count = 0
    for device in lumi_devices:
        if isinstance(device, Light):
            # Create Matter RGB Light adapter
            matter_light = LumiRGBLight(device.name, device)
            matter.add_device(matter_light)
            logger.info(f"Registered RGB Light: {device.name}")
            device_count += 1
        
        # TODO: Add Button support
        # elif isinstance(device, Button):
        #     matter_button = LumiButton(device.name, device)
        #     matter.add_device(matter_button)
        #     logger.info(f"Registered Button: {device.name}")
        #     device_count += 1
    
    if device_count == 0:
        logger.warning("No devices found! Make sure LED devices exist in /sys/class/leds/")
        logger.info("Creating demo mode...")
    
    logger.info(f"\n{'='*60}")
    logger.info("Matter Bridge started successfully!")
    logger.info(f"Registered {device_count} device(s)")
    logger.info(f"{'='*60}\n")
    
    # Main loop - process Matter packets
    try:
        while True:
            matter.process_packets()
    except KeyboardInterrupt:
        logger.info("\nShutting down Matter Bridge...")
        sys.exit(0)


if __name__ == '__main__':
    main()
