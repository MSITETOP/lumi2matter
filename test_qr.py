#!/usr/bin/env python3
"""
Quick test script to verify Matter Bridge QR code generation
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lumimqtt.matter_bridge import LumiMatter

def test_qr_generation():
    """Test QR code generation without starting full bridge"""
    print("Testing Matter Bridge QR Code Generation\n")
    
    # Create a test bridge instance
    bridge = LumiMatter(
        device_id="test_gateway",
        device_name="Test Lumi Gateway",
        vendor_id=0xFFF1,
        product_id=0x8001,
        discriminator=3840,
        passcode=20202021,
    )
    
    # Display pairing info
    bridge._display_pairing_info()
    
    print("\n✅ QR Code generation test successful!")
    print("\nNote: This is just a test. To run the full Matter Bridge:")
    print("  LUMIMQTT_CONFIG=./lumimqtt.json python3 -m lumimqtt")

if __name__ == '__main__':
    test_qr_generation()
