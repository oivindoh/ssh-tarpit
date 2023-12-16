import asyncio
import socket
import weakref
import random
import logging
import time
from prometheus_client import Counter, Gauge

client_connections = Counter('connections', 'Number of connections per source', ['source'])
client_time = Counter('wasted_time', 'Time wasted per source', ['source'])
clients_trapped = Gauge('trapped', 'Number of currently trapped sources')


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
        client_start = time.time()
        client_connections.labels(source=str(peer_addr[0])).inc()
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
            client_stop = time.time()
            wasted_time = client_stop - client_start
            client_time.labels(source=str(peer_addr[0])).inc(wasted_time)
            clients_trapped.dec()
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
