#!/usr/bin/env python3
import psycopg2
import os
import ipaddress
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Database connection details (use environment variables for security)
DB_HOST = os.getenv("DB_HOST", "your-db-host")
DB_NAME = os.getenv("DB_NAME", "your-db-name")
DB_USER = os.getenv("DB_USER", "your-db-user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your-db-password")

# Query to fetch IP addresses from ssh_connections
QUERY = "SELECT DISTINCT client_ip FROM ssh_connections WHERE client_ip IS NOT NULL"

# Namespace where ingress-nginx lives
NAMESPACE = "ingress-nginx"  # Adjust if different
POLICY_NAME = "deny-ssh-ips-to-ingress-nginx"

def fetch_ip_addresses():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cur = conn.cursor()
        cur.execute(QUERY)
        rows = cur.fetchall()
        # Process IPs to normalize IPv4 and preserve IPv6
        ip_list = [normalize_ip(row[0]) for row in rows]
        cur.close()
        conn.close()
        return ip_list
    except Exception as e:
        print(f"Error fetching IPs: {e}")
        return []

def normalize_ip(ip):
    """Normalize IP addresses: IPv4-mapped to pure IPv4, IPv6 preserved."""
    try:
        # If it’s already a CIDR, split base IP and mask
        if "/" in ip:
            base_ip, cidr = ip.split("/", 1)
        else:
            base_ip, cidr = ip, None

        # Parse the base IP
        ip_obj = ipaddress.ip_address(base_ip)

        if ip_obj.version == 4:
            # Pure IPv4 or IPv4-mapped converted to pure IPv4
            return f"{ip_obj}/32" if cidr is None else f"{ip_obj}/{cidr}"
        elif ip_obj.version == 6:
            # Check if it’s an IPv4-mapped IPv6 address
            if ip_obj.is_ipv4_mapped():
                # Extract the IPv4 portion and return as pure IPv4
                ipv4 = ip_obj.ipv4_mapped
                return f"{ipv4}/32" if cidr is None else f"{ipv4}/{cidr}"
            # Pure IPv6 address
            return f"{ip_obj}/128" if cidr is None else f"{ip_obj}/{cidr}"
    except ValueError:
        print(f"Skipping invalid IP address: {ip}")
        return None

def generate_cilium_policy(ip_list):
    # Filter out None values from invalid IPs
    valid_ips = [ip for ip in ip_list if ip is not None]
    if not valid_ips:
        print("No valid IP addresses to include in policy.")
        return None
    return {
        "apiVersion": "cilium.io/v2",
        "kind": "CiliumNetworkPolicy",
        "metadata": {
            "name": POLICY_NAME,
            "namespace": NAMESPACE
        },
        "spec": {
            "endpointSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "ingress-nginx"
                }
            },
            "ingressDeny": [
                {
                    "fromCIDR": valid_ips
                }
            ]
        }
    }

def apply_policy(policy):
    if policy is None:
        print("No policy to apply due to lack of valid IPs.")
        return
    # Load in-cluster config
    config.load_incluster_config()
    custom_api = client.CustomObjectsApi()

    try:
        # Try to update the existing policy
        custom_api.patch_namespaced_custom_object(
            group="cilium.io",
            version="v2",
            namespace=NAMESPACE,
            plural="ciliumnetworkpolicies",
            name=POLICY_NAME,
            body=policy
        )
        print("Cilium Network Policy updated successfully.")
    except ApiException as e:
        if e.status == 404:
            # If it doesn’t exist, create it
            try:
                custom_api.create_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=NAMESPACE,
                    plural="ciliumnetworkpolicies",
                    body=policy
                )
                print("Cilium Network Policy created successfully.")
            except ApiException as create_error:
                print(f"Error creating policy: {create_error}")
        else:
            print(f"Error updating policy: {e}")

if __name__ == "__main__":
    ip_list = fetch_ip_addresses()
    if not ip_list:
        print("No IP addresses found. Exiting without applying policy.")
        exit(0)
    policy = generate_cilium_policy(ip_list)
    apply_policy(policy)
