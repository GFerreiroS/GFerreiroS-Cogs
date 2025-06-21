import asyncio
import json
import os
import pathlib
import platform
import re
import shutil
import socket
import subprocess

import discord

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

from .defaults import create_default_server
from .downloaders import DOWNLOADERS, get_downloader
from .validator import validate_properties


def parse_memory(input_str):
    match = re.match(r"^(\d+)([GM])$", input_str)
    if not match:
        return None
    return match.group(1) + match.group(2)


def find_available_port(start: int = 25565, max_port: int = 65535) -> int:
    for port in range(start, max_port + 1):
        # try both IPv4 and IPv6
        for family in (socket.AF_INET, socket.AF_INET6):
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                # allow immediate reuse
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("", port))
                except OSError:
                    break  # this family is busy → try next family or port
        else:
            # if neither family failed, port is free
            return port
    raise RuntimeError(f"No available port found between {start}–{max_port}")


port = find_available_port(25565)


class MCserver(commands.Cog):
    """Cog for creating and managing Minecraft servers."""

    __author__ = "Gferreiro"
    __version__ = "0.1"

    LAUNCHERS = list(DOWNLOADERS.keys())

    @staticmethod
    def load_sample_properties() -> bytes:
        """Load the sample server.properties from the assets folder."""
        assets_dir = pathlib.Path(__file__).parent / "assets"
        sample = assets_dir / "server.properties"
        return sample.read_bytes()

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321012345678)
        default_guild = {
            "java_path": "java",
            "min_ram": "1024M",
            "max_ram": "2048M",
            "template": "paper",
            "version": "latest",
        }
        self.config.register_guild(**default_guild)

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre = super().format_help_for_context(ctx)
        return f"{pre}\n\nAuthor: {self.__author__}\nVersion: {self.__version__}"

    async def _prompt(self, ctx: commands.Context, prompt: str, check, timeout=60):
        """Helper to send a prompt and wait for response, handling cancellation."""
        await ctx.send(f"{prompt}\n(Type `cancel` to abort.)")
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=timeout)
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out waiting for response. Operation aborted.")
            return None
        content = msg.content.strip()
        if content.lower() == "cancel":
            await ctx.send("❌ Operation cancelled.")
            return None
        return msg

    @commands.command()
    @commands.admin()
    async def createmcserver(self, ctx: commands.Context):
        """Creates a new Minecraft server via interactive prompts."""
        guild_conf = await self.config.guild(ctx.guild).all()

        os_name = platform.system()
        if os_name != "Linux":
            return await ctx.send(
                f"❌ Unsupported OS `{os_name}` detected. Only Linux is supported."
            )

        # Check Java installation
        java_exec = shutil.which("java")
        if not java_exec:
            return await ctx.send(
                "❌ Java is not installed or not in PATH. Please install Java and try again."
            )

        # Get Java version
        try:
            proc = subprocess.run(
                [java_exec, "-version"], capture_output=True, text=True
            )
            version_info = proc.stderr.splitlines()[0]
        except Exception:
            version_info = "Unknown Java version"

        # Check RAM availability via /proc/meminfo
        total_kb = avail_kb = None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
                    if total_kb and avail_kb:
                        break
            total_gb = round(total_kb / 1024 / 1024, 1)
            avail_gb = round(avail_kb / 1024 / 1024, 1)
            ram_info = f"{avail_gb}GB / {total_gb}GB {avail_gb}GB are free"
        except Exception:
            ram_info = "Unknown RAM stats"

        await ctx.send(f"✅ Detected Java: `{version_info}`\n💾 RAM: `{ram_info}`")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # 1) Ask for server name
        name_msg = await self._prompt(
            ctx, "What would you like to name this Minecraft server?", check
        )
        if not name_msg:
            return
        server_name = name_msg.content.strip()

        # Prepare base directory: ~/minecraft-bot/{server_name}
        home = pathlib.Path(os.path.expanduser("~"))
        base_dir = home / "minecraft-bot" / server_name
        try:
            base_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return await ctx.send(
                f"❌ A server named '{server_name}' already exists. Operation aborted."
            )

        eula_msg = await self._prompt(
            ctx,
            "Do you accept the Minecraft EULA? See https://account.mojang.com/documents/minecraft_eula (yes/no)",
            check,
        )
        if not eula_msg or eula_msg.content.lower() not in ("yes", "y"):
            return await ctx.send("❌ You must accept the EULA. Aborting.")
        # Write eula.txt
        (base_dir / "eula.txt").write_text("eula=true")

        # Default options prompt
        resp = await self._prompt(ctx, "Will you use default options? (yes/no)", check)
        if not resp:
            return
        if resp.content.strip().lower() in ("yes", "y"):
            await ctx.send(
                f"Using default configuration. Creating server in `{base_dir}`..."
            )
            return await self._create_with_defaults(ctx, base_dir)

        created_dir = True
        wizard_success = False
        try:
            # Custom options flow
            choice = await self._prompt(
                ctx,
                f"Which launcher will you use? Options: {', '.join(self.LAUNCHERS)}",
                check,
            )
            if not choice:
                return
            launcher = choice.content.strip().lower()
            if launcher not in self.LAUNCHERS:
                return await ctx.send("❌ Invalid launcher. Operation aborted.")

            # fetch available versions as before…
            await ctx.send("Fetching available versions...")
            downloader = get_downloader(launcher)()
            if hasattr(downloader, "get_versions"):
                versions = await downloader.get_versions()
            else:
                versions = await self._get_available_versions(launcher)
            version_list = ", ".join(versions)

            ver_msg = await self._prompt(
                ctx,
                f"Available versions: {version_list}\nWhich version would you like? (or 'latest')",
                check,
            )
            if not ver_msg:
                return
            version = ver_msg.content.strip()
            if version not in versions and version.lower() != "latest":
                return await ctx.send("❌ Invalid version selected. Operation aborted.")

            # Download the chosen server JAR directly into our new server folder
            await ctx.send(
                f"📦 Downloading **{launcher}** server JAR (version `{version}`)…"
            )
            try:
                # first download into temp location
                target_jar = await downloader.fetch(version, dest_dir=base_dir)
            except Exception as e:
                return await ctx.send(f"❌ Failed to download JAR: {e}")
            await ctx.send(f"✅ Download complete: `{target_jar}`")

            # Ask for custom server.properties
            sample_path = pathlib.Path(__file__).parent / "assets" / "server.properties"
            await ctx.send(
                "Please modify this sample server.properties as needed, then attach it. "
                "If you want to use the default, type 'skip'.",
                file=discord.File(sample_path),
            )
            prop_msg = await self._prompt(
                ctx,
                "Attach custom server.properties or type 'skip' to use default",
                check,
            )
            if not prop_msg:
                return
            if prop_msg.content.strip().lower() == "skip":
                props_data = self.load_sample_properties()
            elif prop_msg.attachments:
                att = prop_msg.attachments[0]
                if att.filename != "server.properties":
                    return await ctx.send(
                        "❌ Filename must be server.properties. Aborting."
                    )
                file_bytes = await att.read()
                ok, reason = validate_properties(file_bytes)
                if not ok:
                    return await ctx.send(
                        f"❌ Invalid properties file: {reason}. Aborting."
                    )
                props_data = file_bytes
            else:
                return await ctx.send("❌ No file provided. Aborting.")
            # Write server.properties
            (base_dir / "server.properties").write_bytes(props_data)

            prop_path = base_dir / "server.properties"
            lines = prop_path.read_text().splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("server-port="):
                    new_lines.append(f"server-port={port}")
                elif line.startswith("query.port="):
                    new_lines.append(f"query.port={port}")
                else:
                    new_lines.append(line)

            prop_path.write_text("\n".join(new_lines) + "\n")
            await ctx.send(f"🔌 Port configured: `{port}`")

            # 6) whitelist flag check
            lines = props_data.decode("utf-8").splitlines()
            whitelist_idx = None
            for idx, line in enumerate(lines):
                if line.startswith("white-list="):
                    whitelist_idx = idx
                    break

            skip_whitelist_json = False
            if whitelist_idx is not None:
                val = lines[whitelist_idx].split("=", 1)[1].strip().lower()
                if val == "false":
                    enable_msg = await self._prompt(
                        ctx,
                        "Your server.properties has whitelist disabled. Enable whitelist? (yes/no)",
                        check,
                    )
                    if enable_msg and enable_msg.content.lower() in ("yes", "y"):
                        lines[whitelist_idx] = "white-list=true"
                        new_data = "\n".join(lines).encode("utf-8")
                        (base_dir / "server.properties").write_bytes(new_data)
                        await ctx.send("✅ whitelist set to true.")
                    else:
                        await ctx.send(
                            "⚠️ whitelist remains disabled. Skipping whitelist step."
                        )
                        skip_whitelist_json = True

            # 7) whitelist.json (only if whitelist is enabled)
            if not skip_whitelist_json:
                wl_msg = await self._prompt(
                    ctx, "Attach whitelist.json or type 'skip'", check
                )
                if not wl_msg:
                    return
                if wl_msg.content.strip().lower() == "skip":
                    pass  # continue with no whitelist.json
                elif wl_msg.attachments:
                    att = wl_msg.attachments[0]
                    if att.filename != "whitelist.json":
                        return await ctx.send(
                            "❌ Filename must be whitelist.json. Aborting."
                        )
                    file_bytes = await att.read()
                    try:
                        data = json.loads(file_bytes)
                    except Exception as e:
                        return await ctx.send(f"❌ Invalid JSON: {e}. Aborting.")
                    if not isinstance(data, list):
                        return await ctx.send(
                            "❌ Whitelist must be a JSON array. Aborting."
                        )
                    for i, entry in enumerate(data, 1):
                        if (
                            not isinstance(entry, dict)
                            or "uuid" not in entry
                            or "name" not in entry
                        ):
                            return await ctx.send(
                                f"❌ Invalid entry at position {i}. Aborting."
                            )
                        if not isinstance(entry["uuid"], str) or not isinstance(
                            entry["name"], str
                        ):
                            return await ctx.send(
                                f"❌ Entry {i} fields must be strings. Aborting."
                            )
                    (base_dir / "whitelist.json").write_bytes(file_bytes)
                else:
                    return await ctx.send("❌ No file provided. Aborting.")
            # Ask for minimum RAM
            await ctx.send(
                f"How much minimum RAM would you like? (e.g. '2G' or '512M') Default is {guild_conf.get('min_ram')}."
                f" You have approximately {avail_gb}GB RAM remaining."
            )
            min_msg = await self._prompt(
                ctx, "Enter minimum RAM or type 'skip' to use default:", check
            )
            if not min_msg:
                return
            min_input = min_msg.content.strip()
            if min_input.lower() == "skip":
                min_ram = guild_conf.get("min_ram")
            else:
                pm = parse_memory(min_input)
                if not pm:
                    return await ctx.send(
                        "❌ Invalid format for minimum RAM. Aborting."
                    )
                min_ram = pm

            # Ask for max RAM
            await ctx.send(
                f"How much maximum RAM would you like? (e.g. '4G' or '1024M') Default is {guild_conf.get('max_ram')}."
                f" You have approximately {avail_gb}GB RAM remaining."
            )
            max_msg = await self._prompt(
                ctx, "Enter maximum RAM or type 'skip' to use default:", check
            )
            if not max_msg:
                return
            max_input = max_msg.content.strip()
            if max_input.lower() == "skip":
                max_ram = guild_conf.get("max_ram")
            else:
                pm = parse_memory(max_input)
                if not pm:
                    return await ctx.send(
                        "❌ Invalid format for maximum RAM. Aborting."
                    )
                max_ram = pm

            # Validate that min_ram not greater than max_ram
            # Convert to numeric for comparison
            def to_mb(mem_str):
                num = int(mem_str[:-1])
                return num * (1024 if mem_str.endswith("G") else 1)

            if to_mb(min_ram) > to_mb(max_ram):
                return await ctx.send(
                    "❌ Minimum RAM cannot exceed maximum RAM. Aborting."
                )

            # 8) Java flags configuration
            default_flags = (
                "--add-modules=jdk.incubator.vector -XX:+UseG1GC -XX:+ParallelRefProcEnabled "
                "-XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC "
                "-XX:+AlwaysPreTouch -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 "
                "-XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 "
                "-XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem "
                "-XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs "
                "-Daikars.new.flags=true -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 "
                "-XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20"
            )
            await ctx.send(
                f"Here are the default Java flags:\n ```bash\n {default_flags}\n```"
            )
            flags_msg = await self._prompt(
                ctx,
                "Type 'default' to use these flags, 'none' for no flags, or enter your custom flags separated by spaces:",
                check,
            )
            if not flags_msg:
                return
            flags_input = flags_msg.content.strip()
            if flags_input.lower() == "default":
                flags = default_flags
            elif flags_input.lower() in ("none", "no"):
                flags = ""
            else:
                parts = flags_input.split()
                for part in parts:
                    if not part.startswith("-"):
                        return await ctx.send(
                            f"❌ Invalid flag '{part}'. All flags must start with '-'. Aborting."
                        )
                flags = flags_input

            # 9) Generate run script
            run_choice = await self._prompt(
                ctx,
                "Would you like to generate a monitor‐style start script (run-minecraft.sh)? (yes/no)",
                check,
            )
            if run_choice and run_choice.content.strip().lower() in ("yes", "y"):
                script = f"""#!/usr/bin/env bash
set -euo pipefail

JAR_FILE="server.jar"
MIN_RAM="{min_ram}"
MAX_RAM="{max_ram}"
JAVA_FLAGS="{flags}"
SERVER_NAME="{server_name}"

while true; do
# if the server isn’t running, restart it
if ! screen -S "$SERVER_NAME" -Q select . >/dev/null 2>&1; then
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
                script_path = base_dir / "run-minecraft.sh"
                script_path.write_text(script)
                script_path.chmod(0o755)
                await ctx.send(f"✅ Generated monitor script at `{script_path}`.")

                # Now also generate a kill-server.sh
                kill_script = f"""#!/usr/bin/env bash
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
                kill_path = base_dir / "kill-server.sh"
                kill_path.write_text(kill_script)
                kill_path.chmod(0o755)

                start_server = await self._prompt(
                    ctx,
                    "Do we start the server now? (yes/no)",
                    check,
                )
                if start_server and start_server.content.strip().lower() in (
                    "yes",
                    "y",
                ):
                    run_script = base_dir / "run-minecraft.sh"
                    if not run_script.exists():
                        return await ctx.send(
                            "❌ Run script not found. Cannot start server. Aborting."
                        )
                    try:
                        # Launch the script asynchronously (does not wait for it to finish)
                        proc = await asyncio.create_subprocess_exec(
                            "bash",
                            str(run_script),
                            cwd=str(base_dir),
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                    except Exception as e:
                        return await ctx.send(f"❌ Failed to start server: {e}")
                    else:
                        await ctx.send(
                            f"Your screen session named `{server_name}`. \n"
                            f"To check your server console, connect via ssh and use `screen -r {server_name}`"
                        )
                else:
                    await ctx.send("ℹ️ Skipping start script generation.")

            await ctx.send(f"Server created in `{base_dir}`...")
            wizard_success = True
            return
        finally:
            if not wizard_success and created_dir:
                shutil.rmtree(base_dir, ignore_errors=True)

    @commands.command(name="listservers")
    @commands.admin()
    async def listservers(self, ctx: commands.Context):
        """List all existing Minecraft servers."""
        base = pathlib.Path(os.path.expanduser("~")) / "minecraft-bot"
        if not base.exists():
            return await ctx.send("No servers found.")
        servers = [p.name for p in base.iterdir() if p.is_dir()]
        if not servers:
            return await ctx.send("No servers found.")
        await ctx.send("Available servers:\n" + "\n".join(f"- {s}" for s in servers))

    @commands.group(name="deleteserver", invoke_without_command=True)
    @commands.admin()
    async def deleteserver(self, ctx: commands.Context, name: str = None):
        """Delete a specific Minecraft server folder or use subcommands."""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        base = pathlib.Path(os.path.expanduser("~")) / "minecraft-bot"
        # If no name, list available
        if name is None:
            names = (
                [p.name for p in base.iterdir() if p.is_dir()] if base.exists() else []
            )
            if not names:
                return await ctx.send("No servers to delete.")
            name_msg = await self._prompt(
                ctx, "Pick server to delete:\n" + "\n".join(names), check
            )
            if not name_msg:
                return
            name = name_msg.content.strip()
        # Delete specific server
        target = base / name
        if not target.exists() or not target.is_dir():
            return await ctx.send(f"❌ Server '{name}' not found.")
        conf = await self._prompt(
            ctx, f"Confirm delete server '{name}'? (yes/no)", check
        )
        if not conf or conf.content.lower() not in ("yes", "y"):
            return await ctx.send("Aborted.")
        shutil.rmtree(target)
        await ctx.send(f"✅ Deleted server '{name}'.")

    @deleteserver.command(name="all")
    @commands.admin()
    async def deleteserver_all(self, ctx: commands.Context):
        """Delete all Minecraft server folders."""

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        base = pathlib.Path(os.path.expanduser("~")) / "minecraft-bot"
        if not base.exists():
            return await ctx.send("No servers to delete.")
        names = [p.name for p in base.iterdir() if p.is_dir()]
        if not names:
            return await ctx.send("No servers to delete.")
        confirm = await self._prompt(
            ctx, f"Confirm delete ALL servers ({', '.join(names)})? (yes/no)", check
        )
        if not confirm or confirm.content.lower() not in ("yes", "y"):
            return await ctx.send("Aborted.")
        for sub in names:
            shutil.rmtree(base / sub)
        await ctx.send(f"✅ Deleted all servers: {', '.join(names)}.")

    async def _create_with_defaults(self, ctx, base_dir: pathlib.Path):
        return await create_default_server(ctx, base_dir)

    async def _get_available_versions(self, launcher: str) -> list:
        """Fetch and return a list of available versions for the given launcher."""
        # TODO: use aiohttp to fetch version manifests
        return ["latest"]


async def setup(bot: Red):
    cog = MCserver(bot)
    await bot.add_cog(cog)
