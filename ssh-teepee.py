import asyncio
import socket
import uuid
import psycopg2
from datetime import datetime
import os
import maxminddb
import time
import random

# Database configuration (adjust or use environment variables)
DB_CONFIG = {
    "dbname": os.getenv("TARPIT_DATABASE_DBNAME","postgres"),
    "user": os.getenv("TARPIT_DATABASE_USER","postgres"),
    "password": os.getenv("TARPIT_DATABASE_PASSWORD","your_password"),
    "host": os.getenv("TARPIT_DATABASE_HOST","localhost"),
    "port": "5432"
}

mmdb_path = os.getenv('TARPIT_MMDB_PATH','/GeoLite2-City.mmdb')

if os.path.isfile(mmdb_path):
    GEOIP_DATABASE = maxminddb.open_database(mmdb_path)
    ENRICH = True
    print("IP enrichment enabled")
else:
    ENRICH = False


# Wait for database to be available with retry
def wait_for_db(max_attempts=10, initial_delay=1):
    attempt = 1
    delay = initial_delay
    
    while attempt <= max_attempts:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            conn.close()
            print(f"Database connection successful on attempt {attempt}")
            return True
        except psycopg2.OperationalError as e:
            print(f"Database not ready (attempt {attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                print("Max attempts reached. Exiting.")
                return False
            time.sleep(delay)
            attempt += 1
            delay *= 2  # Exponential backoff: 1s, 2s, 4s, 8s, etc.

# Initialize the database table
def init_db():
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ssh_connections (
                id UUID PRIMARY KEY,
                client_ip INET NOT NULL,
                start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                end_time TIMESTAMP WITH TIME ZONE,
                duration INTERVAL,
                country_code CHAR(2),
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION
            );
        """)
        conn.commit()
    conn.close()

# Insert a new connection
def log_connection_start(conn, client_ip, country_code, latitude, longitude):
    with conn.cursor() as cur:
        conn_id = uuid.uuid4()
        start_time = datetime.utcnow()
        cur.execute("""
            INSERT INTO ssh_connections (id, client_ip, start_time, country_code, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (str(conn_id), client_ip, start_time, country_code, latitude, longitude))
        conn.commit()
    return conn_id

# Update connection on close
def log_connection_end(conn, conn_id):
    with conn.cursor() as cur:
        end_time = datetime.utcnow()
        cur.execute("""
            UPDATE ssh_connections
            SET end_time = %s,
                duration = %s - start_time
            WHERE id = %s;
        """, (end_time, end_time, str(conn_id)))
        conn.commit()

# Get geodata from IP (extract country code and coordinates)
def get_geodata(ip):
    try:
        if ENRICH:
            if ip == "::ffff:172.18.0.1":
                ip = "::ffff:195.88.54.16"
            geodata = GEOIP_DATABASE.get(str(ip))
            if geodata != None:
                country_code = geodata["country"]["iso_code"]  # e.g., 'NO'
                latitude = geodata["location"]["latitude"]     # e.g., 59.9452
                longitude = geodata["location"]["longitude"]   # e.g., 10.7559
                return country_code, latitude, longitude
            else:
                raise Exception(f"No geodata found for client {ip}")
    except Exception as e:
        print(e)
        return None, None, None  # Handle missing geodata

# Async SSH tarpit handler
async def handle_client(reader, writer, db_conn):
    client_addr = writer.get_extra_info('peername')
    client_ip = client_addr[0]
    print(f"New connection from {client_ip}")

    # Log connection start
    country_code, latitude, longitude = get_geodata(client_ip)
    conn_id = log_connection_start(db_conn, client_ip, country_code, latitude, longitude)

    # Disable reading
    writer.transport.pause_reading()
    sock = writer.transport.get_extra_info('socket')
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RD)
        except (TypeError, OSError):
            direct_sock = socket.socket(sock.family, sock.type, sock.proto, sock.fileno())
            try:
                direct_sock.shutdown(socket.SHUT_RD)
            finally:
                direct_sock.detach()

    try:
        while True:
            await asyncio.sleep(1)  # Send every 1 second
            writer.write(b'%.8x\r\n' % random.randrange(2**32))
            await writer.drain()
            #print(f"Sent data to {client_ip}")
    except (ConnectionResetError, BrokenPipeError) as e:
        print(f"Client {client_ip} disconnected: {e}")
    except (RuntimeError, TimeoutError) as e:
        print(f"Terminating connection with {client_ip} due to: {e}")
    except OSError as e:
        print(f"OSError with {client_ip}: {e}")
        if e.errno == 107:  # ENOTCONN
            pass
        else:
            raise
    finally:
        #print(f"Entering finally block for {client_ip}")
        log_connection_end(db_conn, conn_id)
        writer.transport.close()  # Close the transport
        # Skip wait_closed() to avoid BrokenPipeError
        print(f"Connection from {client_ip} closed")


# Main server
async def main():

    if not wait_for_db(max_attempts=10, initial_delay=1):
        print("Failed to connect to database. Exiting.")
        return

    # Initialize database
    init_db()
    db_conn = psycopg2.connect(**DB_CONFIG)

    # Create a dual-stack socket
    server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # Allow IPv4 too
    server_socket.bind(('::', 2222))
    server_socket.listen()

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, db_conn),
        sock=server_socket
    )

    print("SSH grokpit running on [::]:2222")
    
    async with server:
        await server.serve_forever()

    db_conn.close()

if __name__ == "__main__":
    asyncio.run(main())
