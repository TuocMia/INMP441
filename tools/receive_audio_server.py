#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import socket
import struct
import sys
import time


def build_output_path(output_dir: pathlib.Path, prefix: str) -> pathlib.Path:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{prefix}_{timestamp}.wav"


def write_wav_header(output_file, sample_rate: int, channels: int, bits_per_sample: int, data_size: int) -> None:
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    riff_size = 36 + data_size

    output_file.seek(0)
    output_file.write(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            riff_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )
    )


def receive_recording(
    host: str,
    port: int,
    output_path: pathlib.Path,
    sample_rate: int,
    channels: int,
    bits_per_sample: int,
    session_timeout: float,
    seq_header: bool,
) -> None:
    def close_session_if_open(state: dict) -> None:
        output_file = state.get("output_file")
        if output_file is None:
            return

        output_file.flush()
        write_wav_header(output_file, sample_rate, channels, bits_per_sample, state["bytes_received"])
        output_file.close()

        total_elapsed = time.monotonic() - state["start_time"]
        active_elapsed = state["last_packet_time"] - state["start_time"]
        if active_elapsed <= 0:
            active_elapsed = total_elapsed
        rate_kbps = (state["bytes_received"] / 1024) / active_elapsed if active_elapsed > 0 else 0.0
        expected_bps = sample_rate * channels * (bits_per_sample / 8)
        expected_kibps = expected_bps / 1024.0
        ratio = (rate_kbps / expected_kibps) if expected_kibps > 0 else 0.0
        print(
            f"Saved {state['session_path']} ({state['bytes_received']} bytes, "
            f"active {active_elapsed:.2f}s, total {total_elapsed:.2f}s, "
            f"avg {rate_kbps:.1f} KiB/s, packets={state['packet_count']}, lost={state['lost_packets']})"
        )
        print(
            f"Expected ~{expected_kibps:.1f} KiB/s for {sample_rate}Hz/{channels}ch/{bits_per_sample}bit, "
            f"actual ratio={ratio:.2f}"
        )
        if ratio < 0.9:
            print("WARNING: Throughput below expected, likely sample drops/time-compressed audio")

        state["output_file"] = None
        state["last_seq"] = None

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        server_socket.bind((host, port))
        server_socket.settimeout(0.5)
        print(f"Listening UDP on {host}:{port}")

        state = {
            "output_file": None,
            "session_path": None,
            "bytes_received": 0,
            "packet_count": 0,
            "lost_packets": 0,
            "start_time": 0.0,
            "last_log_time": 0.0,
            "last_packet_time": 0.0,
            "last_seq": None,
        }

        while True:
            now = time.monotonic()
            try:
                datagram, address = server_socket.recvfrom(2048)
            except socket.timeout:
                if state["output_file"] is not None and now - state["last_packet_time"] >= session_timeout:
                    print(f"Session timeout ({session_timeout:.1f}s without packets)")
                    close_session_if_open(state)
                continue
            except KeyboardInterrupt:
                close_session_if_open(state)
                raise
            except Exception as exc:
                print(f"Receive error: {exc}", file=sys.stderr)
                continue

            if state["output_file"] is None:
                session_path = output_path
                if session_path.exists():
                    stem = session_path.stem
                    suffix = session_path.suffix
                    session_path = session_path.with_name(
                        f"{stem}_{dt.datetime.now().strftime('%H%M%S')}{suffix}"
                    )
                output_file = session_path.open("w+b", buffering=65536)
                write_wav_header(output_file, sample_rate, channels, bits_per_sample, 0)

                state["output_file"] = output_file
                state["session_path"] = session_path
                state["bytes_received"] = 0
                state["packet_count"] = 0
                state["lost_packets"] = 0
                state["start_time"] = now
                state["last_log_time"] = now
                state["last_seq"] = None

                print(f"Sender detected: {address[0]}:{address[1]}")
                print(f"Saving to {session_path}")

            payload = datagram
            if seq_header:
                if len(datagram) < 4:
                    continue
                seq = struct.unpack("<I", datagram[:4])[0]
                payload = datagram[4:]
                if state["last_seq"] is not None:
                    expected_seq = (state["last_seq"] + 1) & 0xFFFFFFFF
                    if seq != expected_seq:
                        lost = (seq - expected_seq) & 0xFFFFFFFF
                        state["lost_packets"] += lost
                state["last_seq"] = seq

            if not payload:
                continue

            state["output_file"].write(payload)
            state["bytes_received"] += len(payload)
            state["packet_count"] += 1
            state["last_packet_time"] = now

            elapsed = now - state["start_time"]
            if now - state["last_log_time"] >= 1.0:
                rate_kbps = (state["bytes_received"] / 1024) / elapsed if elapsed > 0 else 0.0
                print(
                    f"Pkt #{state['packet_count']}: +{len(payload)} bytes, total={state['bytes_received']} bytes, "
                    f"elapsed={elapsed:.2f}s, avg={rate_kbps:.1f} KiB/s, lost={state['lost_packets']}"
                )
                state["last_log_time"] = now


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive WAV audio from the ESP32 recorder via UDP")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=5000, help="UDP port to listen on, default: 5000")
    parser.add_argument(
        "--output-dir",
        default="recordings",
        help="Directory where the WAV file will be saved, default: recordings",
    )
    parser.add_argument(
        "--prefix",
        default="recording",
        help="Output filename prefix, default: recording",
    )
    parser.add_argument("--sample-rate", type=int, default=16000, help="PCM sample rate, default: 16000")
    parser.add_argument("--channels", type=int, default=1, help="PCM channel count, default: 1")
    parser.add_argument("--bits-per-sample", type=int, default=16, help="PCM bit depth, default: 16")
    parser.add_argument(
        "--session-timeout",
        type=float,
        default=2.0,
        help="Close current WAV after this many seconds without UDP packets, default: 2.0",
    )
    parser.add_argument(
        "--raw-udp",
        action="store_true",
        help="Treat each datagram as raw PCM without 4-byte sequence header",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_output_path(output_dir, args.prefix)

    try:
        receive_recording(
            args.host,
            args.port,
            output_path,
            args.sample_rate,
            args.channels,
            args.bits_per_sample,
            args.session_timeout,
            not args.raw_udp,
        )
    except KeyboardInterrupt:
        print("Interrupted")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
