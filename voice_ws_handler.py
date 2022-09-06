import asyncio
import websockets
import json
import oauth2
import socket
# import nacl.utils
# import nacl.secret
# from pyogg import OpusEncoder
# import wave


class VoiceWebsocketHandler:
    def __init__(self, bot):
        self.bot = bot

        # Voice WebSocket & URI
        self.voice_socket_uri = None
        self.vws = None

        # Voice heartbeat ACK Future
        self.voice_heartbeat_ack = None
        # Voice heartbeat interval
        self.voice_heartbeat_interval = 0

        # Cache variables for received WebSocket payloads
        self.voice_state_cache = None
        self.voice_server_cache = None
        self.udp_details_cache = None
        self.session_desc_cache = None

        # Dictates whether voice state updates are cached
        self.is_joining = None

        # UDP socket and connection details
        self.udp_socket = None
        self.remote_ip = None
        self.remote_port = None
        self.external_ip = None
        self.external_port = None

        # RTP Sync Source
        self.ssrc = None

        # Encryption key
        self.secret_key = None

        # Wave file object
        self.wave_read = None
        # Opus encoder
        self.encoder = None

    async def setup(self):
        await self.bot.loop.create_task(self.voice_join())
        self.bot.loop.create_task(self.voice_heartbeat())
        await self.bot.loop.create_task(self.voice_identify())
        self.bot.loop.create_task(self.voice_monitor())
        await self.bot.loop.create_task(self.discover_ip())
        await self.bot.loop.create_task(self.voice_select())
        self.bot.loop.create_task(self.monitor_udp())

    async def voice_join(self):
        """
        Sends Opcode 4 Gateway Voice State Update, connects to the Voice WebSocket
        and establishes Voice Heartbeat and Identify tasks.
        """
        # Unlock Voice State and Server cache
        self.is_joining = True
        # Wait for WebSocket events
        self.voice_state_cache = self.bot.loop.create_future()
        try:
            await asyncio.wait_for(self.voice_state_cache, timeout=5.0)
        except asyncio.TimeoutError:
            print('Timed out waiting for Voice State Update')
        self.voice_server_cache = self.bot.loop.create_future()
        try:
            await asyncio.wait_for(self.voice_server_cache, timeout=5.0)
        except asyncio.TimeoutError:
            print('Timed out waiting for Voice Server Update')
        # Lock caches
        self.is_joining = False

        # Format Voice WebSocket URI
        self.voice_socket_uri = "wss://{}/?v=4".format(self.voice_server_cache.result()["d"]["endpoint"])
        # Connect to Voice WebSocket
        self.vws = await websockets.connect(self.voice_socket_uri)
        # Await Voice Opcode 8 Hello
        result = await self.vws.recv()
        print(result)
        # Store heartbeat interval from 'Hello' payload
        self.voice_heartbeat_interval = json.loads(result)["d"]["heartbeat_interval"] / 1000
        # Add tasks for Heartbeat and Identify to main event loop

    async def voice_heartbeat(self):
        """
        Sends Voice Opcode 3 Heartbeat at specified interval.
        """
        while True:
            # Wait specified interval
            await asyncio.sleep(self.voice_heartbeat_interval)
            # Create 'Heartbeat' payload
            payload = json.dumps({"op": 3, "d": oauth2.generate_nonce()})
            # Establish Future object to receive ACK
            self.voice_heartbeat_ack = self.bot.loop.create_future()
            # Send payload over Voice WebSocket
            await self.vws.send(payload)
            try:
                # Await ACK
                await asyncio.wait_for(self.voice_heartbeat_ack, timeout=5.0)
            except asyncio.TimeoutError:
                # If ACK not received timeout and disconnect
                # TODO: Implement Voice Resume functionality
                print('Timed out waiting for Voice ACK')
                await self.bot.ws_handler.disconnect()
            print("Received Voice ACK")

    async def voice_identify(self):
        """
        Sends Voice Opcode 0 Identify and establishes Voice Monitor and IP Discovery tasks.
        """
        # Create 'Identify' payload
        payload = json.dumps({"op": 0, "d": {"server_id": self.voice_server_cache.result()["d"]["guild_id"],
                                             "user_id": self.bot.bot_id,
                                             "session_id": self.voice_state_cache.result()["d"]["session_id"],
                                             "token": self.voice_server_cache.result()["d"]["token"]}})
        # Send payload over Voice WebSocket
        await self.vws.send(payload)
        # Await 'Ready' event
        result = await self.vws.recv()
        print(result)
        # Cache Voice Server UDP details
        self.udp_details_cache = json.loads(result)
        # Add tasks for Monitor and IP Discovery to main event loop

    async def voice_monitor(self):
        """
        Awaits incoming messages on the voice Websocket.
        """
        while True:
            result = await self.vws.recv()

            # Voice Opcode 6 Heartbeat ACK
            if json.loads(result)["op"] == 6:
                self.voice_heartbeat_ack.set_result(True)

            # Voice Opcode 4 Session Description
            if json.loads(result)["op"] == 4:
                self.session_desc_cache.set_result(json.loads(result))

    async def discover_ip(self):
        """
        Sends UDP Packet to voice port to discover external IP and port.
        """
        # Create UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Get UDP details from cache
        self.remote_ip = self.udp_details_cache["d"]["ip"]
        self.remote_port = self.udp_details_cache["d"]["port"]
        self.ssrc = self.udp_details_cache["d"]["ssrc"]

        # Create IP Discovery packet
        p_type = (0x1).to_bytes(2, byteorder='big', signed=False)
        p_length = (70).to_bytes(2, byteorder='big', signed=False)
        p_ssrc = self.ssrc.to_bytes(4, byteorder='big', signed=False)
        p_address = bytes(self.remote_ip, 'utf-8')
        p_address_padding = bytes(64 - len(bytes(self.remote_ip, 'utf-8')))
        p_port = self.remote_port.to_bytes(2, byteorder='big', signed=False)

        discovery_packet = b''.join([p_type, p_length, p_ssrc, p_address, p_address_padding, p_port])

        # Send packet
        self.udp_socket.sendto(discovery_packet, (self.remote_ip, self.remote_port))
        # Receive packet
        discovery_packet = self.udp_socket.recvfrom(74)

        # Save external IP and port
        self.external_ip = discovery_packet[0][8:72].decode('utf-8').replace('\u0000', '')
        self.external_port = int.from_bytes(discovery_packet[0][72:74], byteorder='big', signed=False)

        # Add task for Voice Select to main event loop

    async def voice_select(self):
        """
        Sends Voice Opcode 1 Select and establishes UDP Monitor task.
        """
        # Create 'Select' payload
        payload = json.dumps({"op": 1, "d": {"protocol": "udp",
                                             "data": {"address": self.external_ip,
                                                      "port": self.external_port,
                                                      "mode": "xsalsa20_poly1305_suffix"}}})

        print(payload)
        # Send payload over Voice WebSocket
        await self.vws.send(payload)
        # Await Session Description
        self.session_desc_cache = self.bot.loop.create_future()
        try:
            await asyncio.wait_for(self.session_desc_cache, timeout=5.0)
            print(self.session_desc_cache.result())
            # Get Secret Key for encryption
            self.secret_key = self.session_desc_cache.result()["d"]["secret_key"]
        except asyncio.TimeoutError:
            print('Timed out waiting for Session Description')

        # Add task for UDP Monitor to main event loop

    async def monitor_udp(self):
        """
        Awaits incoming UDP packets from voice port.
        """
        while True:
            # TODO: Change method to receive all bytes available into buffer
            x = await self.bot.loop.sock_recv(self.udp_socket, 400)
            print(x)

    # TODO: Toggle Method?
    async def voice_start_speaking(self):
        """
        Sends Voice Opcode 5 Speaking.
        """
        payload = json.dumps({"op": 5, "d": {"speaking": 1,
                                             "delay": 0,
                                             "ssrc": self.ssrc}})
        await self.vws.send(payload)

    """
    # FIXME: Audio packets aren't playing
    async def play_wav(self):
        
        #Plays .WAV file over active voice connection.
        
        await self.voice_start_speaking()
        # libsodium encryption using provided Secret Key
        box = nacl.secret.SecretBox(bytes(self.secret_key))

        # RTP Header fields for audio packet
        p_version = (0x80).to_bytes(1, byteorder='big', signed=False)
        p_type = (0x78).to_bytes(1, byteorder='big', signed=False)
        p_ssrc = self.ssrc.to_bytes(4, byteorder='big', signed=False)

        # Source: https://pyogg.readthedocs.io/en/latest/examples.html#encode-and-decode-opus-packets

        # Open .WAV file in binary-read
        self.wave_read = wave.open('file.wav', 'rb')

        # TODO: Learn digital audio terminology?
        #  Would probably help :(

        # Audio channels (i.e. 1 = mono, 2 = stereo)
        channels = self.wave_read.getnchannels()
        print("Number of channels:", channels)
        # Sample rate in Hz
        samples_per_second = self.wave_read.getframerate()
        print("Sampling frequency:", samples_per_second)
        # Number of bytes in each audio sample
        bytes_per_sample = self.wave_read.getsampwidth()

        self.encoder = OpusEncoder()
        self.encoder.set_application("audio")
        self.encoder.set_sampling_frequency(samples_per_second)  # Can convert to 48kHz here? Hopefully
        self.encoder.set_channels(channels)  # And dual channel?

        desired_frame_duration = 20 / 1000  # Opus uses 20ms frame by default
        desired_frame_size = int(desired_frame_duration * samples_per_second)  # Frame size in number of samples? Gotcha

        # Seq no.
        i = 0
        while True:
            # Return frames of audio as bytes
            pcm = self.wave_read.readframes(desired_frame_size)

            # Empty check
            if len(pcm) == 0:
                break

            # Calculate actual frame size from bytes read
            effective_frame_size = (
                    len(pcm)
                    // bytes_per_sample
                    // channels
            )

            # Frame padding
            if effective_frame_size < desired_frame_size:
                pcm += (
                        b"\x00"
                        * ((desired_frame_size - effective_frame_size)
                           * bytes_per_sample
                           * channels)
                )

            # Encode PCM bytes
            encoded_payload = self.encoder.encode(pcm)

            print(encoded_payload.tobytes())

            # Final RTP Header fields
            p_sequence = i.to_bytes(2, byteorder='big', signed=False)
            p_timestamp = (random.randint(1, 100) + (i * desired_frame_size)).to_bytes(4, byteorder='big', signed=False)

            rtp_header = b''.join([p_version, p_type, p_sequence, p_timestamp, p_ssrc])  # Form header
            encrypted_payload = box.encrypt(encoded_payload.tobytes(), nacl.utils.random(24))  # Encrypt payload
            audio_packet = b''.join([rtp_header, encrypted_payload])  # Form packet

            print(audio_packet)

            self.udp_socket.sendto(audio_packet, (self.remote_ip, self.remote_port))  # Send audio packet
            i += 1  # Increment seq no.
            await asyncio.sleep(0.02)  # Wait 20ms
    """

