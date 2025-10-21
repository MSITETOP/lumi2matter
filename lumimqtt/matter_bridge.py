"""
Lightweight Matter Bridge for Lumi Gateway
Similar to Tasmota Matter implementation - minimal, efficient approach
"""

import asyncio as aio
import json
import logging
import typing as ty
from dataclasses import dataclass
from datetime import datetime
from zeroconf import ServiceInfo, Zeroconf
from zeroconf.asyncio import AsyncZeroconf
import qrcode
import socket
import struct

from .__version__ import version
from .button import Button
from .device import Device
from .light import Light

logger = logging.getLogger(__name__)

# Matter constants (from Matter spec)
MATTER_PORT = 5540
MATTER_VENDOR_ID = 0xFFF1  # Test vendor ID
MATTER_PRODUCT_ID = 0x8001  # Gateway product
MATTER_DISCRIMINATOR = 3840  # Default discriminator


@dataclass
class MatterEndpoint:
    """Matter endpoint representation"""
    endpoint_id: int
    device_type: int
    clusters: ty.List[int]
    device: Device


class MatterDeviceType:
    """Matter device type IDs"""
    ROOT_NODE = 0x0016
    EXTENDED_COLOR_LIGHT = 0x010D  # RGB light with full color control
    ON_OFF_LIGHT = 0x0100
    GENERIC_SWITCH = 0x000F  # Momentary switch (button)


class MatterCluster:
    """Matter cluster IDs"""
    # Common clusters
    DESCRIPTOR = 0x001D
    IDENTIFY = 0x0003
    GROUPS = 0x0004
    SCENES = 0x0005
    
    # Light clusters
    ON_OFF = 0x0006
    LEVEL_CONTROL = 0x0008
    COLOR_CONTROL = 0x0300
    
    # Switch clusters
    SWITCH = 0x003B


class LumiMatter:
    """
    Lightweight Matter Bridge for Xiaomi Lumi Gateway
    Implements a minimal Matter server similar to Tasmota approach
    """
    
    def __init__(
        self,
        device_id: str,
        device_name: str,
        *,
        vendor_id: int = MATTER_VENDOR_ID,
        product_id: int = MATTER_PRODUCT_ID,
        discriminator: int = MATTER_DISCRIMINATOR,
        passcode: int = 20202021,
        port: int = MATTER_PORT,
    ) -> None:
        self.dev_id = device_id
        self.device_name = device_name
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.discriminator = discriminator
        self.passcode = passcode
        self.port = port
        
        # Device storage
        self.lights: ty.List[Light] = []
        self.buttons: ty.List[Button] = []
        self.endpoints: ty.List[MatterEndpoint] = []
        
        # Matter service
        self.zeroconf: ty.Optional[AsyncZeroconf] = None
        self.service_info: ty.Optional[ServiceInfo] = None
        
        # State
        self._commissioned = False
        self._fabric_id: ty.Optional[int] = None
        self._tasks: ty.List[aio.Task] = []
        
        # UDP server for Matter protocol
        self._udp_transport: ty.Optional[aio.DatagramTransport] = None
        self._udp_protocol: ty.Optional['MatterUDPProtocol'] = None
        
        # Setup root endpoint (endpoint 0)
        self._setup_root_endpoint()
    
    def _setup_root_endpoint(self):
        """Setup Matter root node endpoint"""
        root_endpoint = MatterEndpoint(
            endpoint_id=0,
            device_type=MatterDeviceType.ROOT_NODE,
            clusters=[
                MatterCluster.DESCRIPTOR,
                MatterCluster.IDENTIFY,
            ],
            device=None
        )
        self.endpoints.append(root_endpoint)
    
    def register(self, device: Device):
        """Register a device and create Matter endpoint"""
        if not device:
            return
        
        endpoint_id = len(self.endpoints)
        
        if isinstance(device, Light):
            # Register as Extended Color Light (RGB)
            endpoint = MatterEndpoint(
                endpoint_id=endpoint_id,
                device_type=MatterDeviceType.EXTENDED_COLOR_LIGHT,
                clusters=[
                    MatterCluster.DESCRIPTOR,
                    MatterCluster.IDENTIFY,
                    MatterCluster.ON_OFF,
                    MatterCluster.LEVEL_CONTROL,
                    MatterCluster.COLOR_CONTROL,
                ],
                device=device
            )
            self.lights.append(device)
            self.endpoints.append(endpoint)
            logger.info(f"Registered RGB Light on endpoint {endpoint_id}")
            
        elif isinstance(device, Button):
            # Register as Generic Switch (momentary button)
            endpoint = MatterEndpoint(
                endpoint_id=endpoint_id,
                device_type=MatterDeviceType.GENERIC_SWITCH,
                clusters=[
                    MatterCluster.DESCRIPTOR,
                    MatterCluster.IDENTIFY,
                    MatterCluster.SWITCH,
                ],
                device=device
            )
            self.buttons.append(device)
            self.endpoints.append(endpoint)
            logger.info(f"Registered Button on endpoint {endpoint_id}")
    
    async def start(self):
        """Start Matter bridge"""
        logger.info(f"Starting Matter Bridge for device {self.dev_id}")
        
        # Start UDP server for Matter protocol
        await self._start_udp_server()
        
        # Start mDNS service discovery
        await self._start_mdns()
        
        # Start device handlers
        self._tasks = [
            aio.create_task(self._handle_buttons()),
            aio.create_task(self._handle_lights()),
            aio.create_task(self._handle_commissioning()),
        ]
        
        # Wait for tasks
        finished, _ = await aio.wait(
            self._tasks,
            return_when=aio.FIRST_COMPLETED,
        )
        for t in finished:
            t.result()
    
    async def close(self) -> None:
        """Stop Matter bridge"""
        logger.info("Stopping Matter Bridge")
        
        # Stop UDP server
        if self._udp_transport:
            self._udp_transport.close()
        
        # Stop mDNS
        if self.zeroconf:
            await self._stop_mdns()
        
        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except aio.CancelledError:
                    pass
    
    async def _start_mdns(self):
        """Start mDNS advertisement for Matter device discovery"""
        self.zeroconf = AsyncZeroconf()
        
        # Matter service type
        service_type = "_matter._tcp.local."
        service_name = f"{self.device_name}.{service_type}"
        
        # Matter TXT records for commissioning
        txt_records = {
            "D": str(self.discriminator),  # Discriminator
            "VP": f"{self.vendor_id}+{self.product_id}",  # Vendor+Product
            "CM": "1" if not self._commissioned else "0",  # Commissioning mode
            "DT": "65535",  # Device type (bridge)
            "DN": self.device_name,  # Device name
            "SII": "5000",  # Sleep Idle Interval
            "SAI": "300",  # Sleep Active Interval
        }
        
        # Create service info
        self.service_info = ServiceInfo(
            type_=service_type,
            name=service_name,
            port=self.port,
            properties=txt_records,
            server=f"{self.dev_id}.local.",
        )
        
        # Register service
        await self.zeroconf.async_register_service(self.service_info)
        logger.info(f"Matter device advertised via mDNS: {service_name}")
        
        # Display pairing information
        self._display_pairing_info()
    
    async def _stop_mdns(self):
        """Stop mDNS advertisement"""
        if self.service_info:
            await self.zeroconf.async_unregister_service(self.service_info)
        await self.zeroconf.async_close()
    
    def _generate_qr_code(self) -> str:
        """Generate Matter QR code payload for pairing"""
        # Matter QR code format: MT:<base38-encoded-payload>
        # Payload structure (bits):
        # Version (3 bits) | VID (16 bits) | PID (16 bits) | 
        # Custom Flow (2 bits) | Discovery Caps (8 bits) |
        # Discriminator (12 bits) | Passcode (27 bits)
        
        version = 0  # Matter version
        vid = self.vendor_id
        pid = self.product_id
        custom_flow = 0  # Standard commissioning
        discovery_caps = 0x04  # On Network (BLE=0x01, SoftAP=0x02, OnNetwork=0x04)
        discriminator = self.discriminator
        passcode = self.passcode
        
        # Pack into bits
        # Total: 3 + 16 + 16 + 2 + 8 + 12 + 27 = 84 bits
        value = 0
        value |= (version & 0x7) << 81  # 3 bits at position 81
        value |= (vid & 0xFFFF) << 65   # 16 bits at position 65
        value |= (pid & 0xFFFF) << 49   # 16 bits at position 49
        value |= (custom_flow & 0x3) << 47  # 2 bits at position 47
        value |= (discovery_caps & 0xFF) << 39  # 8 bits at position 39
        value |= (discriminator & 0xFFF) << 27  # 12 bits at position 27
        value |= (passcode & 0x7FFFFFF)  # 27 bits at position 0
        
        # Convert to base-38 encoded string
        base38_chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."
        encoded = ""
        
        # Encode the value in base-38
        temp_value = value
        while temp_value > 0:
            encoded = base38_chars[temp_value % 38] + encoded
            temp_value //= 38
        
        # Pad to ensure minimum length (should be ~15-20 chars for Matter QR)
        while len(encoded) < 20:
            encoded = "0" + encoded
        
        # Matter QR code format
        qr_payload = f"MT:{encoded}"
        
        return qr_payload
    
    def _display_pairing_info(self):
        """Display pairing QR code and manual code"""
        qr_payload = self._generate_qr_code()
        
        # Generate manual pairing code (11 digits)
        # Matter format: XXXX-XXX-XXXX (as expected by Yandex Station)
        manual_code_value = self.passcode
        manual_code_str = f"{manual_code_value:011d}"  # Pad to 11 digits
        manual_code = f"{manual_code_str[0:4]}-{manual_code_str[4:7]}-{manual_code_str[7:11]}"
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(qr_payload)
        qr.make(fit=True)
        
        # Print to console
        print("\n" + "="*60)
        print("🔗 MATTER DEVICE PAIRING INFORMATION")
        print("="*60)
        print(f"Device Name: {self.device_name}")
        print(f"Device ID: {self.dev_id}")
        print(f"Vendor ID: 0x{self.vendor_id:04X} ({self.vendor_id})")
        print(f"Product ID: 0x{self.product_id:04X} ({self.product_id})")
        print("-"*60)
        print(f"📱 Manual Pairing Code: {manual_code}")
        print(f"   (Enter in Yandex Station as XXXX-XXX-XXXX)")
        print(f"🔢 Discriminator: {self.discriminator}")
        print(f"🔐 Setup PIN: {self.passcode}")
        print("-"*60)
        print("📷 QR Code - scan with Yandex Station:")
        print(f"QR Payload: {qr_payload}")
        print()
        
        # Print QR code to console
        qr.print_ascii(invert=True)
        
        print()
        print("="*60)
        print("ℹ️  Instructions:")
        print("1. Open Yandex Station app")
        print("2. Go to 'Add Device' -> 'Matter'")
        print("3. OPTION A: Scan QR code above")
        print(f"4. OPTION B: Enter manual code: {manual_code}")
        print("5. Follow on-screen instructions")
        print("="*60)
        print()
        
        logger.info(f"Manual pairing code (XXXX-XXX-XXXX format): {manual_code}")
        logger.info(f"QR payload: {qr_payload}")
    
    async def _handle_commissioning(self):
        """Handle Matter commissioning process"""
        while True:
            # In a real implementation, this would handle:
            # 1. PASE (Password Authenticated Session Establishment)
            # 2. Certificate exchange
            # 3. Fabric joining
            # 
            # For now, we'll simulate commissioning state
            await aio.sleep(5)
            
            # TODO: Implement actual Matter commissioning protocol
            # This requires handling UDP packets on port 5540
    
    async def _handle_buttons(self):
        """Handle button events and map to Matter Switch cluster"""
        tasks = [
            aio.create_task(button.handle(self._on_button_event))
            for button in self.buttons
        ]
        
        if not tasks:
            # No buttons, sleep forever
            await aio.Event().wait()
            return
        
        try:
            finished, unfinished = await aio.wait(
                tasks,
                return_when=aio.FIRST_COMPLETED,
            )
        except aio.CancelledError:
            for t in tasks:
                t.cancel()
                try:
                    await t
                except aio.CancelledError:
                    pass
            raise
        
        for t in unfinished:
            t.cancel()
            try:
                await t
            except aio.CancelledError:
                pass
        
        for t in finished:
            t.result()
    
    async def _on_button_event(self, button: Button, action: str):
        """Handle button action and send Matter event"""
        logger.info(f"Button {button.name} action: {action}")
        
        # Map button actions to Matter Switch events
        # Matter Switch cluster supports:
        # - InitialPress (0x00)
        # - LongPress (0x01)
        # - ShortRelease (0x02)
        # - LongRelease (0x03)
        # - MultiPressOngoing (0x04)
        # - MultiPressComplete (0x05)
        
        matter_event = self._map_button_action_to_matter(action)
        
        # Find endpoint for this button
        endpoint = next(
            (ep for ep in self.endpoints if ep.device == button),
            None
        )
        
        if endpoint:
            # TODO: Send Matter event notification
            # In real implementation, this would send to all subscribed controllers
            logger.debug(
                f"Matter event on endpoint {endpoint.endpoint_id}: "
                f"Switch cluster event {matter_event}"
            )
    
    def _map_button_action_to_matter(self, action: str) -> int:
        """Map lumimqtt button action to Matter Switch event"""
        mapping = {
            'single': 0x02,  # ShortRelease
            'double': 0x05,  # MultiPressComplete (2 presses)
            'triple': 0x05,  # MultiPressComplete (3 presses)
            'hold': 0x01,    # LongPress
            'release': 0x03, # LongRelease
        }
        return mapping.get(action, 0x00)
    
    async def _handle_lights(self):
        """Monitor light state changes"""
        while True:
            await aio.sleep(1)
            # Lights are controlled via Matter commands
            # This task monitors for state changes and updates endpoints
    
    async def handle_light_command(
        self,
        endpoint_id: int,
        cluster_id: int,
        command_id: int,
        args: dict
    ):
        """Handle Matter light control commands"""
        endpoint = next(
            (ep for ep in self.endpoints if ep.endpoint_id == endpoint_id),
            None
        )
        
        if not endpoint or not isinstance(endpoint.device, Light):
            logger.error(f"Invalid light endpoint: {endpoint_id}")
            return
        
        light: Light = endpoint.device
        
        # Handle OnOff cluster (0x0006)
        if cluster_id == MatterCluster.ON_OFF:
            if command_id == 0x00:  # Off
                await light.set({'state': 'OFF'}, 0)
            elif command_id == 0x01:  # On
                await light.set({'state': 'ON'}, 0)
            elif command_id == 0x02:  # Toggle
                new_state = 'OFF' if light.state['state'] == 'ON' else 'ON'
                await light.set({'state': new_state}, 0)
        
        # Handle LevelControl cluster (0x0008) - Brightness
        elif cluster_id == MatterCluster.LEVEL_CONTROL:
            if command_id == 0x00:  # MoveToLevel
                level = args.get('level', 255)
                transition = args.get('transition_time', 0) / 10  # Convert to seconds
                await light.set({'brightness': level}, transition)
        
        # Handle ColorControl cluster (0x0300) - RGB Color
        elif cluster_id == MatterCluster.COLOR_CONTROL:
            if command_id == 0x47:  # MoveToHueAndSaturation
                # Convert HSV to RGB
                hue = args.get('hue', 0)
                saturation = args.get('saturation', 0)
                rgb = self._hsv_to_rgb(hue / 254 * 360, saturation / 254 * 100, 100)
                await light.set({
                    'color': {'r': rgb[0], 'g': rgb[1], 'b': rgb[2]}
                }, 0)
    
    @staticmethod
    def _hsv_to_rgb(h: float, s: float, v: float) -> ty.Tuple[int, int, int]:
        """Convert HSV to RGB (0-255)"""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
        return int(r * 255), int(g * 255), int(b * 255)
    
    async def _start_udp_server(self):
        """Start UDP server for Matter protocol on port 5540"""
        loop = aio.get_running_loop()
        
        # Create UDP endpoint
        self._udp_protocol = MatterUDPProtocol(self)
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: self._udp_protocol,
            local_addr=('0.0.0.0', self.port)
        )
        self._udp_transport = transport
        
        logger.info(f"Matter UDP server started on port {self.port}")


class MatterUDPProtocol(aio.DatagramProtocol):
    """UDP protocol handler for Matter messages"""
    
    def __init__(self, bridge: LumiMatter):
        self.bridge = bridge
        self.transport: ty.Optional[aio.DatagramTransport] = None
    
    def connection_made(self, transport):
        self.transport = transport
        logger.debug("Matter UDP protocol ready")
    
    def datagram_received(self, data: bytes, addr: ty.Tuple[str, int]):
        """Handle incoming Matter UDP packets"""
        logger.info(f"Received Matter packet from {addr[0]}:{addr[1]}, size: {len(data)} bytes")
        
        # Parse Matter message
        try:
            message = self._parse_matter_message(data)
            logger.debug(f"Matter message: {message}")
            
            # Handle message based on type
            response = self._handle_matter_message(message, addr)
            
            if response:
                # Send response
                self.transport.sendto(response, addr)
                logger.debug(f"Sent Matter response to {addr[0]}:{addr[1]}, size: {len(response)} bytes")
        
        except Exception as e:
            logger.error(f"Error processing Matter message: {e}", exc_info=True)
    
    def _parse_matter_message(self, data: bytes) -> dict:
        """Parse Matter protocol message (simplified)"""
        if len(data) < 8:
            raise ValueError("Message too short")
        
        # Matter message structure (simplified):
        # Byte 0: Message flags
        # Byte 1-2: Session ID
        # Byte 3: Security flags
        # Byte 4-7: Message counter
        # Byte 8+: Payload
        
        flags = data[0]
        session_id = struct.unpack('<H', data[1:3])[0]
        security_flags = data[3]
        message_counter = struct.unpack('<I', data[4:8])[0]
        payload = data[8:]
        
        return {
            'flags': flags,
            'session_id': session_id,
            'security_flags': security_flags,
            'message_counter': message_counter,
            'payload': payload,
        }
    
    def _handle_matter_message(self, message: dict, addr: ty.Tuple[str, int]) -> ty.Optional[bytes]:
        """Handle Matter message and generate response"""
        
        # Check if this is a commissioning message (session_id = 0)
        if message['session_id'] == 0:
            logger.info("Received commissioning message")
            return self._handle_commissioning_message(message, addr)
        
        # Handle other messages
        logger.debug(f"Received operational message on session {message['session_id']}")
        return None
    
    def _handle_commissioning_message(self, message: dict, addr: ty.Tuple[str, int]) -> bytes:
        """Handle PASE commissioning message (simplified)"""
        
        payload = message['payload']
        
        # Try to parse Protocol Opcode from payload
        if len(payload) < 4:
            logger.warning("Commissioning payload too short")
            return self._build_status_response(message, status=0x01)  # Failure
        
        # Extract protocol opcode (byte 0-1 of secure channel protocol)
        # This is very simplified - real implementation would parse TLV structure
        
        logger.info(f"Processing PASE commissioning (payload size: {len(payload)} bytes)")
        
        # For now, send a simple acknowledgment
        # Real implementation would:
        # 1. Parse PBKDFParamRequest
        # 2. Send PBKDFParamResponse
        # 3. Handle Pake1, Pake2, Pake3 messages
        # 4. Establish secure session
        
        # Send basic acknowledgment
        return self._build_pase_response(message)
    
    def _build_pase_response(self, request: dict) -> bytes:
        """Build PASE response message (very simplified)"""
        
        # Build Matter message header
        flags = 0x00  # Unsecured message
        session_id = 0  # Commissioning session
        security_flags = 0x00
        message_counter = request['message_counter'] + 1
        
        # Very basic payload - real implementation would include:
        # - PBKDF parameters (iterations, salt)
        # - PAKE verifier
        # - Session parameters
        
        # For now, send minimal response to show we're listening
        payload = b'\x15\x30\x01\x00'  # Minimal TLV structure
        
        # Pack message
        response = struct.pack('<BHB', flags, session_id, security_flags)
        response += struct.pack('<I', message_counter)
        response += payload
        
        logger.info("Sent PASE response (simplified)")
        return response
    
    def _build_status_response(self, request: dict, status: int) -> bytes:
        """Build status response message"""
        
        flags = 0x00
        session_id = request['session_id']
        security_flags = 0x00
        message_counter = request['message_counter'] + 1
        
        # Status report payload
        payload = struct.pack('<B', status)
        
        response = struct.pack('<BHB', flags, session_id, security_flags)
        response += struct.pack('<I', message_counter)
        response += payload
        
        return response
    
    def error_received(self, exc):
        logger.error(f"UDP error: {exc}")
    
    def connection_lost(self, exc):
        logger.info("Matter UDP protocol closed")
