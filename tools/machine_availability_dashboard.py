import subprocess
import platform
import pandas as pd
import socket
import streamlit as st
from datetime import datetime
from streamlit import st_autorefresh

def ping_host(host):
    """
    Pings a host and returns True if reachable, False otherwise.
    """
    # Determine the parameter based on the OS
    param = '-n' if platform.system().lower() == 'windows' else '-c'
    # Build the ping command
    command = ['ping', param, '1', host]
    
    try:
        # Suppress the output
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception:
        # In case of any exception, consider the host unreachable
        return False

def get_ip_address(host):
    """
    Retrieves the IP address of a host.
    """
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return "N/A"

@st.cache_data  # Replaces st.experimental_memo
def generate_machine_status(prefix, start_num, end_num):
    """
    Generate status for machines with configurable prefix and number range.
    """
    # Generate the list of machine names based on prefix and range
    machine_names = [f'{prefix}-{i:02d}' for i in range(start_num, end_num + 1)]
    
    # Ping each machine and collect results
    results = []
    for machine in machine_names:
        reachable = ping_host(machine)
        status = 'Reachable' if reachable else 'Unreachable'
        ip_address = get_ip_address(machine)
        results.append({'Machine': machine, 'Status': status, 'IP Address': ip_address})
    
    # Create a DataFrame for a nicely formatted report
    df = pd.DataFrame(results)
    return df

# Streamlit App Configuration
st.set_page_config(page_title="Machine Availability Dashboard", layout="centered")

st.title("🖥️ Machine Availability Dashboard")

# Add configuration inputs in a sidebar
st.sidebar.header("Configuration")
prefix = st.sidebar.text_input("Machine Name Prefix", value="HEC")
start_num = st.sidebar.number_input("Starting Number", value=1, min_value=1)
end_num = st.sidebar.number_input("Ending Number", value=18, min_value=1)

if end_num < start_num:
    st.error("Ending number must be greater than or equal to starting number!")
else:
    # Auto-refresh every 60 seconds (60000 milliseconds)
    count = st_autorefresh(interval=60 * 1000, key="refresh")

    # Display the last updated time
    st.write(f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Generate and display the machine status
    df = generate_machine_status(prefix, start_num, end_num)

    # Function to apply color styling
    def color_status(val):
        color = 'green' if val == 'Reachable' else 'red'
        return f'color: {color}'

    # Apply styling to the DataFrame
    styled_df = df.style.applymap(color_status, subset=['Status']) \
                            .set_table_styles(
                                [{'selector': 'th', 'props': [('background-color', '#f2f2f2')]}]
                            ) \
                            .set_properties(**{
                                'text-align': 'center',
                                'font-family': 'Arial',
                                'font-size': '12px'
                            })

    st.dataframe(styled_df)
