# st-app.py
# launches a streamlit app for the dashboard with all graphs
from get_data import connect_to
import streamlit as st
import pandas as pd
import time
from datetime import datetime

# class to hold server information
class ServerInfo:
	def __init__(self, name: str, addr: str, port: int, tab: st.delta_generator = None):
		self.name = name
		self.addr = addr
		self.port = port
		self.tab = tab

	def __str__(self):
		return f"name: {self.name}; address: {self.addr}:{self.port}"

# constants for server info
SERVERS = {
	"cb": ServerInfo("cbrown", "10.0.1.2", 6767),
	"sw": ServerInfo("sw-server", "10.0.2.2", 6767),
	"ah": ServerInfo("ahays-server", "10.0.3.2", 6767),
	"rm": ServerInfo("rmoses", "10.0.4.2", 6767),
}

METRICS = ["cpu", "vm", "disk", "io_r", "io_w"]

# default alert thresholds, one per metric
# cpu / vm / disk are percents; io_r / io_w are bytes per sample (~per second)
DEFAULT_THRESHOLDS = {
	"cpu": 80.0,
	"vm": 85.0,
	"disk": 90.0,
	"io_r": 50000000.0,
	"io_w": 50000000.0,
}


st.header("Linux Infrastructure Observabililty Dashboard", width="content")

# ---- notifications: threshold settings in the sidebar ----
st.sidebar.header("Alert Thresholds")
thresholds = {}
for metric in METRICS:
	thresholds[metric] = st.sidebar.number_input(
		f"{metric} max",
		value=DEFAULT_THRESHOLDS[metric],
		key=f"thresh_{metric}",
	)

if "alert_log" not in st.session_state:
	st.session_state["alert_log"] = []
if "active_alerts" not in st.session_state:
	st.session_state["active_alerts"] = set()

# alert history gets its own fragment so it refreshes every 5 seconds
# instead of only when the main page reruns
@st.fragment(run_every="5s")
def alert_history():
	with st.sidebar:
		st.header("Alert History")
		if st.session_state["alert_log"]:
			for entry in reversed(st.session_state["alert_log"][-10:]):
				st.write(entry)
		else:
			st.write("No alerts yet.")

alert_history()

# select options
col1, col2 = st.columns(2)

with col1:
	current_metrics = st.multiselect("Metrics:", METRICS, default="cpu")

with col2:
	history_len = st.number_input("History Length:", min_value=60, value=120)

# tabs for each server
SERVERS["cb"].tab, SERVERS["sw"].tab, SERVERS["ah"].tab, SERVERS["rm"].tab = st.tabs([
	SERVERS["cb"].name,
	SERVERS["sw"].name,
	SERVERS["ah"].name,
	SERVERS["rm"].name,
])

if "data" not in st.session_state:
	st.session_state["data"] = {
		server.addr: pd.DataFrame({"time": pd.Series(dtype=float), **{metric: pd.Series(dtype=float) for metric in METRICS}}) for server in SERVERS.values()
	}

# compare the newest reading against the thresholds.
# a breach fires a toast + a history entry ONCE when it starts,
# then clears itself when the value drops back under the threshold.
def check_thresholds(server, stats):
	for metric in METRICS:
		value = stats.get(metric)
		if value is None:
			continue
		key = (server.name, metric)
		if value >= thresholds[metric]:
			if key not in st.session_state["active_alerts"]:
				st.session_state["active_alerts"].add(key)
				msg = f"{server.name}: {metric} at {value:.1f} (threshold {thresholds[metric]:.1f})"
				st.toast(msg, icon="⚠️")
				st.session_state["alert_log"].append(
					f"{datetime.now().strftime('%H:%M:%S')} — {msg}"
				)
		else:
			st.session_state["active_alerts"].discard(key)

# fetch data using connect_to() every 5 seconds.
# FIX v2 for duplicate graphs: the st.empty() placeholder is created
# INSIDE the fragment. A fragment rerun replaces everything the
# fragment produced last time, so the placeholder + chart get swapped
# out as one block. (v1 created the placeholder outside the fragment;
# the fragment's writes then appended instead of replacing, and a
# stale chart survived every refresh.)
def update_data(server):
	@st.fragment(run_every="5s")
	def render():
		slot = st.empty()
		with slot.container():
			try:
				stats = connect_to(server.addr, server.port)
				st.session_state["data"][server.addr] = pd.concat([st.session_state["data"][server.addr], pd.DataFrame([stats])])
				check_thresholds(server, stats)
			except RuntimeError as e: st.error(e)
			# persistent red banner in this server's tab while any metric is over
			for (name, metric) in sorted(st.session_state["active_alerts"]):
				if name == server.name:
					st.error(f"⚠️ {metric} is over its alert threshold")
			df = st.session_state["data"][server.addr]
			df = df[df["time"] > time.time() - history_len]
			df = df.assign(time=pd.to_datetime(df["time"], unit="s"))
			st.area_chart(df, x="time", y=current_metrics)

	render()

for server in SERVERS.values():
	with server.tab:
		update_data(server)
