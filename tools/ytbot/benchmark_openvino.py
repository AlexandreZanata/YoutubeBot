"""Isolated benchmark entry point for the same local OpenVINO worker."""

from pathlib import Path


def main():
    if "flowbench-" not in Path("/proc/self/cgroup").read_text():
        raise ValueError("OpenVINO experiment requires its isolated benchmark unit.")
    from .openvino_engine import main as run
    run()


if __name__ == "__main__":
    main()
