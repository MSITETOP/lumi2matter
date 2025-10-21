"""
Matter Bridge entry point for Lumi Gateway
Run with: python3 -m lumimqtt
"""

import asyncio as aio
import json
import logging
import os
import sys
from pathlib import Path

from .matter_bridge import LumiMatter
from .platform import devices

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


async def main():
    """Main entry point"""
    logger.info("Starting Lumi Matter Bridge")
    
    # Load configuration
    config = load_config()
    
    # Get device ID
    device_id = config.get('device_id', 'lumi_gateway')
    device_name = config.get('device_name', 'Lumi Gateway')
    
    # Matter configuration
    matter_config = config.get('matter', {})
    vendor_id = matter_config.get('vendor_id', 0xFFF1)
    product_id = matter_config.get('product_id', 0x8001)
    discriminator = matter_config.get('discriminator', 3840)
    passcode = matter_config.get('passcode', 20202021)
    
    # Create Matter bridge
    bridge = LumiMatter(
        device_id=device_id,
        device_name=device_name,
        vendor_id=vendor_id,
        product_id=product_id,
        discriminator=discriminator,
        passcode=passcode,
    )
    
    # Register devices (lights and buttons)
    binary_sensors = config.get('binary_sensors', {})
    custom_commands = config.get('custom_commands', {})
    
    for device in devices(binary_sensors, custom_commands):
        bridge.register(device)
    
    logger.info(f"Registered {len(bridge.lights)} lights and {len(bridge.buttons)} buttons")
    
    # Start bridge
    try:
        await bridge.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bridge.close()


def run():
    """Run the main async loop"""
    try:
        aio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)


if __name__ == '__main__':
    run()
