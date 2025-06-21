import asyncio
import pathlib
import platform
import socket

from .downloaders import get_downloader


async def create_default_server(ctx, base_dir: pathlib.Path):
    """
    Download and configure a default Paper server in base_dir, then
    generate monitor‐style start and kill scripts, and finally launch it.
    """

    os_name = platform.system()
    if os_name != "Linux":
        return await ctx.send(
            f"❌ Unsupported OS `{os_name}` detected. Only Linux is supported."
        )

    server_name = base_dir.name

    # 1) Download latest Paper JAR
    downloader = get_downloader("paper")()
    # first, figure out what "latest" actually is
    versions = await downloader.get_versions()
    if not versions:
        return await ctx.send("❌ Could not retrieve Paper versions.")
    real_version = versions[-1]
    await ctx.send(f"🟩 Using Minecraft version `{real_version}`")

    await ctx.send("⬇️ Downloading Paper server JAR…")
    try:
        jar_path = await downloader.fetch(real_version, dest_dir=base_dir)
    except Exception as e:
        return await ctx.send(f"❌ Failed to download default Paper JAR: {e}")
    await ctx.send(f"✅ Downloaded to `{jar_path}`")

    # 2) Write default server.properties + auto‐choose port
    sample = (
        pathlib.Path(__file__).parent / "assets" / "server.properties"
    ).read_bytes()

    def find_port(start=25565, max_port=65535):
        for p in range(start, max_port + 1):
            for fam in (socket.AF_INET, socket.AF_INET6):
                with socket.socket(fam, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    try:
                        s.bind(("", p))
                    except OSError:
                        break
            else:
                return p
        raise RuntimeError("No free port found")

    port = find_port()
    lines = sample.decode("utf-8").splitlines()
    out = []
    for L in lines:
        if L.startswith("server-port="):
            out.append(f"server-port={port}")
        elif L.startswith("query.port="):
            out.append(f"query.port={port}")
        else:
            out.append(L)
    prop_path = base_dir / "server.properties"
    prop_path.write_text("\n".join(out) + "\n")
    await ctx.send(f"🔌 Wrote server.properties with port `{port}`")

    # 3) Generate scripts
    min_ram = "1024M"
    max_ram = "4096M"
    flags = (
        "--add-modules=jdk.incubator.vector -XX:+UseG1GC -XX:+ParallelRefProcEnabled "
        "-XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC "
        "-XX:+AlwaysPreTouch -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
        "-XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 "
        "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem "
        "-XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs "
        "-Daikars.new.flags=true -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 "
        "-XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20"
    )

    # monitor script
    monitor = f"""#!/usr/bin/env bash
set -euo pipefail

JAR_FILE="server.jar"
MIN_RAM="{min_ram}"
MAX_RAM="{max_ram}"
JAVA_FLAGS="{flags}"
SERVER_NAME="{server_name}"

while true; do
# if the server isn’t running, restart it
if ! pgrep -f "$JAR_FILE nogui" >/dev/null; then
    echo "$(date): server down, restarting…" >> monitor.log

    # validate memory syntax
    if [[ ! "$MIN_RAM" =~ ^[0-9]+[GM]$ ]]; then
    echo "ERROR: XMS ('$MIN_RAM') must be a number ending in 'M' or 'G'." >&2
    exit 1
    fi
    if [[ ! "$MAX_RAM" =~ ^[0-9]+[GM]$ ]]; then
    echo "ERROR: XMX ('$MAX_RAM') must be a number ending in 'M' or 'G'." >&2
    exit 1
    fi

    # ensure JAR exists
    if [ ! -f "$JAR_FILE" ]; then
    echo "ERROR: Could not find jar file '$JAR_FILE'." >&2
    exit 1
    fi

    # ensure java is available
    if ! command -v java >/dev/null 2>&1; then
    echo "ERROR: 'java' not found. Install Java JRE/JDK and try again." >&2
    exit 1
    fi

    # launch inside screen
    screen -DmS "$SERVER_NAME" \\
    java -Xms"$MIN_RAM" -Xmx"$MAX_RAM" $JAVA_FLAGS \\
    -jar "$JAR_FILE" nogui
fi

# wait before checking again
sleep 60
done
                """
    run_sh = base_dir / "run-minecraft.sh"
    run_sh.write_text(monitor)
    run_sh.chmod(0o755)
    await ctx.send(f"✅ Generated monitor script `{run_sh}`")

    # kill script
    killer = f"""#!/usr/bin/env bash
# kill-server.sh: stops Minecraft and the monitor loop

# Name of the screen session
SCREEN_NAME="{server_name}"

# Send the 'stop' command to the server console
screen -S "$SCREEN_NAME" -p 0 -X stuff "stop$(printf '\\r')"

# Quit the screen session entirely
screen -S "$SCREEN_NAME" -X quit

# Kill any running monitor loop
pkill -f "run-minecraft.sh" || true
"""
    kill_sh = base_dir / "kill-server.sh"
    kill_sh.write_text(killer)
    kill_sh.chmod(0o755)
    await ctx.send(f"✅ Generated kill script `{kill_sh}`")

    # 4) Final confirmation
    await ctx.send(
        f"🎉 Default Paper server scaffolded in `{base_dir}` on port {port}."
    )

    # 5) Launch the server via the monitor script
    if run_sh.exists():
        try:
            proc = await asyncio.create_subprocess_exec(
                str(run_sh),
                cwd=str(base_dir),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception as e:
            return await ctx.send(f"❌ Failed to start server: {e}")
        await ctx.send(
            f"🚀 Server launch script started (PID {proc.pid}).\n"
            f"Check the `screen` session named `minecraft-{server_name}`."
        )
    else:
        await ctx.send("❌ Could not find run-minecraft.sh to start the server.")
