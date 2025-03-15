#!/usr/bin/env python3
import psycopg2
import os
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Database connection details (use environment variables for security)
DB_HOST = os.getenv("DB_HOST", "your-db-host")
DB_NAME = os.getenv("DB_NAME", "your-db-name")
DB_USER = os.getenv("DB_USER", "your-db-user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "your-db-password")

# Query to fetch IP addresses from ssh_connections
QUERY = "SELECT DISTINCT ip_address FROM ssh_connections WHERE ip_address IS NOT NULL"

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
        # Extract IPs and append /32 for CIDR notation
        ip_list = [f"{row[0]}/32" for row in rows]
        cur.close()
        conn.close()
        return ip_list
    except Exception as e:
        print(f"Error fetching IPs: {e}")
        return []

def generate_cilium_policy(ip_list):
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
                    "fromCIDR": ip_list
                }
            ]
        }
    }

def apply_policy(policy):
    # Load in-cluster config (assumes the pod has a service account with permissions)
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
            # If it doesn't exist, create it
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
