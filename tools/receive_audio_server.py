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
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64KB recv buffer
        server_socket.bind((host, port))
        server_socket.listen(5)
        server_socket.settimeout(None)
        print(f"Listening on {host}:{port}")

        while True:
            try:
                connection, address = server_socket.accept()
                connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"Accept error: {exc}", file=sys.stderr)
                continue
                
            session_path = output_path
            if session_path.exists():
                stem = session_path.stem
                suffix = session_path.suffix
                session_path = session_path.with_name(f"{stem}_{dt.datetime.now().strftime('%H%M%S')}{suffix}")
            print(f"Client connected: {address[0]}:{address[1]}")
            print(f"Saving to {session_path}")
            
            bytes_received = 0
            chunk_count = 0
            start_time = time.monotonic()
            last_log_time = start_time
            try:
                with connection, session_path.open("w+b", buffering=65536) as output_file:
                    write_wav_header(output_file, sample_rate, channels, bits_per_sample, 0)
                    while True:
                        chunk = connection.recv(16384)  # Tăng chunk size lên 16KB
                        if not chunk:
                            break
                        chunk_count += 1
                        output_file.write(chunk)
                        bytes_received += len(chunk)
                        now = time.monotonic()
                        elapsed = now - start_time
                        if now - last_log_time >= 1.0:
                            rate_kbps = (bytes_received / 1024) / elapsed if elapsed > 0 else 0.0
                            print(
                                f"Chunk #{chunk_count}: +{len(chunk)} bytes, total={bytes_received} bytes, "
                                f"elapsed={elapsed:.2f}s, avg={rate_kbps:.1f} KiB/s"
                            )
                            last_log_time = now
                    write_wav_header(output_file, sample_rate, channels, bits_per_sample, bytes_received)
                total_elapsed = time.monotonic() - start_time
                rate_kbps = (bytes_received / 1024) / total_elapsed if total_elapsed > 0 else 0.0
                expected_bps = sample_rate * channels * (bits_per_sample / 8)
                expected_kibps = expected_bps / 1024.0
                ratio = (rate_kbps / expected_kibps) if expected_kibps > 0 else 0.0
                print(
                    f"Saved {session_path} ({bytes_received} bytes in {total_elapsed:.2f}s, "
                    f"avg {rate_kbps:.1f} KiB/s, chunks={chunk_count})"
                )
                print(
                    f"Expected ~{expected_kibps:.1f} KiB/s for {sample_rate}Hz/{channels}ch/{bits_per_sample}bit, "
                    f"actual ratio={ratio:.2f}"
                )
                if ratio < 0.9:
                    print("WARNING: Throughput below expected, likely sample drops/time-compressed audio")
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"Connection error: {exc}", file=sys.stderr)
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive WAV audio from the ESP32 recorder")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind, default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on, default: 5000")
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
        )
    except KeyboardInterrupt:
        print("Interrupted")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
