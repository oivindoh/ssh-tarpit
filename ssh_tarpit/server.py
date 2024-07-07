import asyncio
import socket
import weakref
import random
import logging
import time
from prometheus_client import Counter, Gauge, Summary
import maxminddb
from os import path,getenv


client_connections = Counter('connections', 'Number of connections per source', ['source','latitude','longitude'])
client_time = Counter('wasted_time', 'Time wasted per source', ['source','latitude','longitude'])
clients_trapped = Gauge('trapped', 'Number of currently trapped sources')
client_time_histogram = Summary('trapped_histogram', 'trapped_histogram', ['source','latitude','longitude'])

connections = {}

class TarpitServer:
    SHUTDOWN_TIMEOUT = 5

    def __init__(self, *,
                 address,
                 port,
                 dualstack=False,
                 interval=2.,
                 loop=None):
        self._loop = loop if loop is not None else asyncio.get_event_loop()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._address = address
        self._port = port
        self._dualstack = dualstack
        self._interval = interval
        self._children = weakref.WeakSet()
        self._mmdb_path = getenv('TARPIT_MMDB_PATH','/GeoLite2-City.mmdb')
        if path.isfile(self._mmdb_path):
            self._mm = maxminddb.open_database(self._mmdb_path)
            self._enrich = True
            self._logger.info("IP enrichment enabled")
        else:
            self._enrich = False
            

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()
        if self._children:
            self._logger.debug("Cancelling %d client handlers...",
                               len(self._children))
            for task in self._children:
                task.cancel()
            await asyncio.wait(self._children)

    async def handler(self, reader, writer):
        writer.transport.pause_reading()
        sock = writer.transport.get_extra_info('socket')
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RD)
            except TypeError:
                direct_sock = socket.socket(sock.family, sock.type, sock.proto, sock.fileno())
                try:
                    direct_sock.shutdown(socket.SHUT_RD)
                finally:
                    direct_sock.detach()
        peer_addr = writer.transport.get_extra_info('peername')
        src_peer = peer_addr[0]
        src_port = peer_addr[1]
        src_latitude = "0.0"
        src_longitude = "0.0"
        client_start = time.time()
        if self._enrich:
            try:
                self._logger.info('attempting enrich')
                geodata = self._mm.get(str(src_peer))
                if "location" in geodata.keys():
                    src_latitude = geodata['location']['latitude']
                    src_longitude = geodata['location']['longitude']
            except:
                self._logger.info('failed to look up geodata')
                pass
        labels = {
            "source": src_peer,
            "longitude": src_longitude,
            "latitude": src_latitude
        }
        client_connections.labels(**labels).inc()
        clients_trapped.inc()
        self._logger.info("Client %s connected", str(peer_addr))
        try:
            while True:
                await asyncio.sleep(self._interval)
                writer.write(b'%.8x\r\n' % random.randrange(2**32))
                await writer.drain()
        except (ConnectionResetError, RuntimeError, TimeoutError) as e:
            self._logger.debug('Terminating handler coro with error: %s',
                               str(e))
        except OSError as e:
            self._logger.debug('Terminating handler coro with error: %s',
                               str(e))
            if e.errno == 107:
                pass
            else:
                raise
        finally:
            wasted_time = time.time() - client_start
            client_time.labels(**labels).inc(wasted_time)
            clients_trapped.dec()
            client_time_histogram.labels(**labels).observe(wasted_time)
            self._logger.info(f"Client {str(peer_addr)} disconnected after {wasted_time}s")

    async def start(self):
        def _spawn(reader, writer):
            self._children.add(
                self._loop.create_task(self.handler(reader, writer)))

        if self._dualstack:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind((self._address, self._port))
            self._server = await asyncio.start_server(_spawn, sock=sock)
        else:
            self._server = await asyncio.start_server(_spawn,
                                                      self._address,
                                                      self._port,
                                                      reuse_address=True)
        self._logger.info("Server ready.")
