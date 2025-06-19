import asyncio
import json
import os
import pathlib
import pwd
import re
import shutil
import subprocess

import discord

from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config

from .downloaders import DOWNLOADERS, get_downloader
from .validator import validate_properties


def parse_memory(input_str):
    match = re.match(r"^(\d+)([GM])$", input_str)
    if not match:
        return None
    return match.group(1) + match.group(2)


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
            remain_gb = round(total_gb - avail_gb, 1)
            ram_info = f"{avail_gb}GB / {total_gb}GB {remain_gb}GB available"
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

            await ctx.send("Fetching available versions...")
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

            eula_msg = await self._prompt(
                ctx,
                "Do you accept the Minecraft EULA? See https://account.mojang.com/documents/minecraft_eula (yes/no)",
                check,
            )
            if not eula_msg or eula_msg.content.lower() not in ("yes", "y"):
                return await ctx.send("❌ You must accept the EULA. Aborting.")
            # Write eula.txt
            (base_dir / "eula.txt").write_text("eula=true")

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
                f" You have approximately {remain_gb}GB RAM remaining."
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
                f" You have approximately {remain_gb}GB RAM remaining."
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
                "Would you like to generate a start script (run-minecraft.sh)? (yes/no)",
                check,
            )
            if run_choice and run_choice.content.strip().lower() in ("yes", "y"):
                script = f"""
                #!/usr/bin/env bash
    
                set -euo pipefail
                
                JAR_FILE=\"server.jar\"
                MIN_RAM=\"{min_ram}\"
                MAX_RAM=\"{max_ram}\"
                JAVA_FLAGS=\"{flags}\" 
                
                if [[ ! \"$MIN_RAM\" =~ ^[0-9]+[GM]$ ]]; then
                echo \"ERROR: XMS ('$MIN_RAM') must be a number ending in 'M' or 'G'.\" >&2
                exit 1
                fi
                if [[ ! \"$MAX_RAM\" =~ ^[0-9]+[GM]$ ]]; then
                echo \"ERROR: XMX ('$MAX_RAM') must be a number ending in 'M' or 'G'.\" >&2
                exit 1
                fi
                
                if [ ! -f \"$JAR_FILE\" ]; then
                echo \"ERROR: Could not find jar file '$JAR_FILE'.\" >&2
                exit 1
                fi
                
                if ! command -v java >/dev/null 2>&1; then
                echo \"ERROR: 'java' command not found. Install Java JRE/JDK and try again.\" >&2
                exit 1
                fi
                
                echo \"Starting Minecraft server\"
                exec java -Xms"$MIN_RAM" -Xmx"$MAX_RAM" $JAVA_FLAGS -jar "$JAR_FILE" nogui
                """
                script_path = base_dir / "run-minecraft.sh"
                script_path.write_text(script)
                await ctx.send(f"✅ Generated start script at `{script_path}`.")
            else:
                await ctx.send("ℹ️ Skipping start script generation.")

            # 11) Service installation
            svc = await self._prompt(
                ctx,
                "Would you like to install a screen‐based service for this server? (yes/no)",
                check,
            )
            if svc and svc.content.strip().lower() in ("yes", "y"):
                # 11a) Require `screen` to be already installed
                if not shutil.which("screen"):
                    # detect distro for install hint
                    distro = {}
                    with open("/etc/os-release") as f:
                        for line in f:
                            if "=" in line:
                                k, v = line.strip().split("=", 1)
                                distro[k] = v.strip('"')
                    dist_id = distro.get("ID", "").lower()
                    install_cmd = None
                    if dist_id in ("ubuntu", "debian"):
                        install_cmd = "sudo apt-get install -y screen"
                    elif dist_id == "fedora":
                        install_cmd = "sudo dnf install -y screen"
                    elif dist_id in ("rhel", "centos"):
                        install_cmd = "sudo yum install -y screen"
                    elif dist_id in ("arch", "cachyos"):
                        install_cmd = "sudo pacman -S --noconfirm screen"
                    elif dist_id in ("opensuse", "sles"):
                        install_cmd = "sudo zypper install -y screen"
                    elif dist_id == "alpine":
                        install_cmd = "sudo apk add screen"
                    elif dist_id == "gentoo":
                        install_cmd = "sudo emerge --ask screen"

                    if install_cmd:
                        return await ctx.send(
                            "❌ `screen` is not installed. Please install it with:\n"
                            f"```bash\n{install_cmd}\n```"
                        )
                    else:
                        return await ctx.send(
                            "❌ `screen` is not installed and I don't know your distro. "
                            "Please install `screen` manually and rerun this command."
                        )
                # 11b) Detect init system and install service
                current_user = pwd.getpwuid(os.geteuid()).pw_name
                assets = pathlib.Path(__file__).parent / "assets"
                if shutil.which("systemctl"):
                    # systemd
                    tmpl = (assets / "service_systemd").read_text()
                    content = (
                        tmpl.replace("User=minecraft", f"User={current_user}")
                        .replace("Group=minecraft", f"Group={current_user}")
                        .replace(
                            "WorkingDirectory=/home/minecraft/server",
                            f"WorkingDirectory={base_dir}",
                        )
                    )
                    dst = (
                        pathlib.Path("/etc/systemd/system")
                        / f"minecraft-{server_name}.service"
                    )
                    dst.write_text(content)
                    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=False)
                    subprocess.run(
                        ["sudo", "systemctl", "enable", f"minecraft-{server_name}"],
                        check=False,
                    )
                    await ctx.send(
                        f"✅ Systemd service installed as `minecraft-{server_name}.service`."
                    )
                elif shutil.which("rc-service") or shutil.which("openrc-run"):
                    # OpenRC
                    tmpl = (assets / "service_openrc").read_text()
                    content = tmpl.replace(
                        'command_user="{$USER}:{$USER}"',
                        f'command_user="{current_user}:{current_user}"',
                    ).replace(
                        "/home/minecraft/server/run-minecraft.sh",
                        str(base_dir / "run-minecraft.sh"),
                    )
                    dst = pathlib.Path("/etc/init.d") / f"minecraft-{server_name}"
                    dst.write_text(content)
                    subprocess.run(["sudo", "chmod", "+x", str(dst)], check=False)
                    subprocess.run(
                        [
                            "sudo",
                            "rc-update",
                            "add",
                            f"minecraft-{server_name}",
                            "default",
                        ],
                        check=False,
                    )
                    await ctx.send(
                        f"✅ OpenRC service installed as `minecraft-{server_name}`."
                    )
                elif shutil.which("service"):
                    # SysVinit
                    tmpl = (assets / "service_sysvinit").read_text()
                    content = tmpl.replace(
                        'MINECRAFT_USER="$USER"', f'MINECRAFT_USER="{current_user}"'
                    ).replace(
                        'MINECRAFT_HOME="/home/minecraft/server"',
                        f'MINECRAFT_HOME="{base_dir}"',
                    )
                    dst = pathlib.Path("/etc/init.d") / f"minecraft-{server_name}"
                    dst.write_text(content)
                    subprocess.run(["sudo", "chmod", "+x", str(dst)], check=False)
                    subprocess.run(
                        ["sudo", "update-rc.d", f"minecraft-{server_name}", "defaults"],
                        check=False,
                    )
                    await ctx.send(
                        f"✅ SysVinit service installed as `minecraft-{server_name}`."
                    )
                else:
                    await ctx.send("⚠️ Unsupported init system. Skipping service setup.")
            else:
                await ctx.send("ℹ️ Skipping service installation.")

            await ctx.send(
                f"Selected launcher: **{launcher}**, version: **{version}**. "
                f"Creating server in `{base_dir}`..."
            )
            return await self._create_custom(ctx, base_dir, launcher, version)
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

    async def _create_with_defaults(
        self, ctx: commands.Context, base_dir: pathlib.Path
    ):
        """Handle server creation using default settings."""
        # TODO: implement default server creation logic in base_dir
        await ctx.send(f"[Stub] Default server created at `{base_dir}`.")

    async def _get_available_versions(self, launcher: str) -> list:
        """Fetch and return a list of available versions for the given launcher."""
        # TODO: use aiohttp to fetch version manifests
        return ["latest"]

    async def _create_custom(
        self, ctx: commands.Context, base_dir: pathlib.Path, launcher: str, version: str
    ):
        """Handle server creation with user-specified launcher and version."""
        downloader = get_downloader(launcher)()
        try:
            jar_path = await downloader.fetch(version)
        except Exception as e:
            return await ctx.send(f"Download failed: {e}")
        # … then write eula.txt, properties, spawn server, etc. …
        await ctx.send(f"Server JAR saved to `{jar_path}`. Continuing setup…")


async def setup(bot: Red):
    cog = MCserver(bot)
    await bot.add_cog(cog)
