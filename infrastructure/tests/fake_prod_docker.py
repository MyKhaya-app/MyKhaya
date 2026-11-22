#!/usr/bin/env python3
"""A fake `docker` for the PROD cutover tests: synthetic, no daemon.

Every Compose model question (`compose config`, `--hash`, `version`) goes to
the REAL Docker CLI, so what gets recreated, and with which environment, is
decided by Compose itself. Only the daemon is simulated: containers, images,
volumes, PostgreSQL answers and the key-directory probe live in a JSON state
file. Every invocation is logged with the cutover state it observed, so tests
can assert exactly what ran and when. Nothing touches a real container.

Environment: FAKE_STATE, FAKE_LOG, REAL_DOCKER, FAKE_CUTOVER_STATE_FILE,
FAKE_FAIL_ON (substring) / FAKE_FAIL_CODE, FAKE_KEY_OWNER (uid:gid),
FAKE_TOUCH_ON_UP (path), FAKE_ENV_FILE_LABEL (value, or __absent__).
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_STATE"])
LOG = Path(os.environ["FAKE_LOG"])
REAL = os.environ["REAL_DOCKER"]
VALUE_OPTIONS = {"-f", "--file", "--env-file", "-p", "--project-name", "--profile",
                 "--project-directory", "--ansi", "--progress"}


def load() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def log(args: list[str]) -> None:
    cutover = os.environ.get("FAKE_CUTOVER_STATE_FILE", "")
    observed = "none"
    if cutover and Path(cutover).is_file():
        observed = (Path(cutover).read_text(encoding="utf-8").splitlines() or ["none"])[0]
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(args).replace("\n", " ")[:400] + f" | state={observed}\n")


def real(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([REAL, *args], capture_output=True, text=True, check=False)


def passthrough(args: list[str]) -> None:
    result = real(args)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode)


def split_compose(args: list[str]) -> tuple[list[str], str, list[str]]:
    index = 1
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in VALUE_OPTIONS else 1
    if index >= len(args):
        return args[1:], "", []
    return args[1:index], args[index], args[index + 1:]


def env_files(global_args: list[str]) -> list[str]:
    return [global_args[i + 1] for i, a in enumerate(global_args) if a == "--env-file"]


def model(global_args: list[str]) -> dict:
    result = real(["compose", *global_args, "config", "--format", "json"])
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(result.returncode)
    return json.loads(result.stdout)


def config_hash(global_args: list[str], service: str) -> str:
    result = real(["compose", *global_args, "config", f"--hash={service}"])
    return result.stdout.split()[-1] if result.returncode == 0 else "unknown"


def mounts_for(definition: dict, volumes: dict, project: str) -> list[dict]:
    mounts = []
    for mount in definition.get("volumes") or []:
        if mount.get("type") == "volume":
            key = mount["source"]
            name = (volumes.get(key) or {}).get("name") or f"{project}_{key}"
            mounts.append({"Type": "volume", "Name": name, "Destination": mount["target"]})
        else:
            mounts.append({"Type": "bind", "Source": mount["source"], "Destination": mount["target"]})
    return mounts


def compose_up(global_args: list[str], rest: list[str], state: dict) -> None:
    flags = {a for a in rest if a.startswith("-")}
    wanted = [a for a in rest if not a.startswith("-")]
    resolved = model(global_args)
    services, project = resolved["services"], resolved["name"]
    order: list[str] = []

    def visit(name: str) -> None:
        if name in order or name not in services:
            return
        if "--no-deps" not in flags:
            for dependency in (services[name].get("depends_on") or {}):
                visit(dependency)
        order.append(name)

    for name in wanted:
        visit(name)
    touch = os.environ.get("FAKE_TOUCH_ON_UP")
    if touch:
        # Simulates key material being replaced while containers change.
        stamp = Path(touch).stat()
        os.utime(touch, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
    for name in order:
        if name in {"migrate", "test"}:
            log(["(dependency run)", name])
            continue
        definition = services[name]
        new_hash = config_hash(global_args, name)
        current = state["containers"].get(name)
        label = (current or {}).get("Labels", {}).get("com.docker.compose.config-hash")
        if current and label == new_hash and "--force-recreate" not in flags:
            continue
        for volume in definition.get("volumes") or []:
            if volume.get("type") == "volume":
                key = volume["source"]
                real_name = (resolved.get("volumes", {}).get(key) or {}).get("name") or f"{project}_{key}"
                state["volumes"].setdefault(real_name, {"CreatedAt": f"created-{secrets.token_hex(3)}",
                                                        "Labels": {"com.docker.compose.project": project}})
        image = definition.get("image") or f"{project}-{name}"
        details = state["images"].get(image, {"Id": f"sha256:{image}", "Env": {}})
        env = dict(details.get("Env", {}))
        env.update({k: ("" if v is None else str(v).replace("$$", "$"))
                    for k, v in (definition.get("environment") or {}).items()})
        labels = {"com.docker.compose.project": project, "com.docker.compose.service": name,
                  "com.docker.compose.oneoff": "False",
                  "com.docker.compose.config-hash": new_hash,
                  "com.docker.compose.project.environment_file": ",".join(env_files(global_args))}
        # FAKE_ENV_FILE_LABEL simulates a Compose that records the label
        # differently (or not at all, with the value __absent__).
        override = os.environ.get("FAKE_ENV_FILE_LABEL")
        if override == "__absent__":
            del labels["com.docker.compose.project.environment_file"]
        elif override is not None:
            labels["com.docker.compose.project.environment_file"] = override
        state["containers"][name] = {
            "Id": f"{name}-{secrets.token_hex(6)}", "Image": details["Id"], "Env": env,
            "Running": True, "Mounts": mounts_for(definition, resolved.get("volumes", {}), project),
            "Labels": labels,
        }
        state.setdefault("recreated", []).append(name)
        log(["(recreated)", name])


def as_inspect(container: dict) -> dict:
    return {"Id": container["Id"], "Image": container["Image"],
            "Config": {"Env": [f"{k}={v}" for k, v in container["Env"].items()],
                       "Labels": container["Labels"]},
            "Mounts": container["Mounts"],
            "State": {"Running": container["Running"], "Status": "running",
                      "Health": {"Status": "healthy"}}}


def by_id(state: dict, identifier: str) -> dict | None:
    return next((c for c in state["containers"].values() if c["Id"] == identifier), None)


def probe(args: list[str]) -> None:
    source = next(a for a in args if a.startswith("type=bind,source="))
    source = source[len("type=bind,source="):].split(",target=")[0]
    uid, gid = (int(x) for x in os.environ.get("FAKE_KEY_OWNER", "0:10001").split(":"))

    def describe(path: Path, name: str) -> dict:
        info = path.lstat()
        kind = ("symlink" if stat.S_ISLNK(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode)
                else "file" if stat.S_ISREG(info.st_mode) else "other")
        return {"name": name, "kind": kind, "mode": stat.S_IMODE(info.st_mode), "uid": uid,
                "gid": gid, "inode": info.st_ino, "size": info.st_size,
                "mtime_ns": info.st_mtime_ns, "readable": kind in {"file", "directory"}}

    root = Path(source)
    if not root.exists():
        print(json.dumps({"uid": 10001, "gid": 10001, "groups": [10001], "error": "missing"}))
        return
    print(json.dumps({"uid": 10001, "gid": 10001, "groups": [10001],
                      "root": describe(root, "."),
                      "entries": [describe(root / n, n) for n in sorted(os.listdir(root))]}))


def psql(sql: str, state: dict) -> None:
    if "alembic_version" in sql:
        print(state["alembic"])
    elif "backup_runs" in sql:
        print(state["backup_run"])
    elif "home_migration_packages" in sql:
        print(state["in_flight"])
    else:
        sys.exit(1)


def main() -> None:
    args = sys.argv[1:]
    log(args)
    fragment = os.environ.get("FAKE_FAIL_ON")
    if fragment and fragment in " ".join(args):
        sys.exit(int(os.environ.get("FAKE_FAIL_CODE", "1")))
    state = load()
    if not args:
        sys.exit(1)
    if args[0] == "compose":
        global_args, sub, rest = split_compose(args)
        if sub in {"config", "version", ""}:
            passthrough(args)
        if sub == "up":
            compose_up(global_args, rest, state)
            save(state)
            return
        if sub in {"run", "build", "images", "logs"}:
            if sub == "images":
                print("\n".join(i["Id"] for i in state["images"].values()))
            if sub == "build":
                state["built"] = True
                save(state)
            return
        if sub == "ps":
            names = [a for a in rest if not a.startswith("-") and a != "running"]
            for name in names or state["containers"]:
                container = state["containers"].get(name)
                if container and container["Running"]:
                    print(container["Id"])
            return
        if sub == "exec":
            psql(rest[-1], state)
            return
        if sub == "down":
            # Destruction is observable: -v/--volumes removes the project's
            # volumes and their artefacts, as the real daemon would.
            project = model(global_args)["name"]
            state["containers"] = {}
            if {"-v", "--volumes"} & set(rest):
                state["volumes"] = {n: v for n, v in state["volumes"].items()
                                    if v.get("Labels", {}).get("com.docker.compose.project") != project}
            save(state)
            return
        sys.exit(0)
    if args[0] == "info":
        print(json.dumps({"SecurityOptions": ["name=seccomp,profile=builtin"],
                          "DockerRootDir": os.environ.get("FAKE_DOCKER_ROOT", "/")}))
        return
    if args[0] == "inspect":
        ids = [a for a in args[1:] if not a.startswith("-")]
        print(json.dumps([as_inspect(c) for c in (by_id(state, i) for i in ids) if c]))
        return
    if args[:2] == ["image", "inspect"]:
        name = args[-1]
        details = state["images"].get(name)
        if details is None:
            sys.stderr.write("Error: No such image\n")
            sys.exit(1)
        labels = details.get("Labels", {})
        if "--format" in args:
            template = args[args.index("--format") + 1]
            if ".Config.User" in template:
                print('"10001:10001"')
            else:
                print(" ".join(labels.get(f"org.opencontainers.image.{k}", "")
                               for k in ("version", "revision", "created")))
            return
        print(json.dumps([{"Id": details["Id"], "Config": {
            "Labels": labels, "User": "10001:10001",
            "Env": [f"{k}={v}" for k, v in details.get("Env", {}).items()]}}]))
        return
    if args[0] == "ps":
        filters = [args[i + 1] for i, a in enumerate(args) if a == "--filter"]
        for container in state["containers"].values():
            ok = True
            for flt in filters:
                key, _, value = flt.partition("=")
                if key == "label":
                    name, _, wanted = value.partition("=")
                    ok &= container["Labels"].get(name) == wanted
                elif key == "volume":
                    ok &= any(m.get("Name") == value for m in container["Mounts"])
            if ok:
                print(container["Id"])
        return
    if args[:2] == ["volume", "ls"]:
        print("\n".join(state["volumes"]))
        return
    if args[:2] == ["volume", "rm"]:
        for name in (a for a in args[2:] if not a.startswith("-")):
            state["volumes"].pop(name, None)
        save(state)
        return
    if args[:2] == ["volume", "inspect"]:
        volume = state["volumes"].get(args[-1])
        if volume is None:
            sys.exit(1)
        print(json.dumps([{"Name": args[-1], **volume}]))
        return
    if args[0] == "exec":
        psql(args[-1], state)
        return
    if args[0] == "run":
        if "app.mykhaya.probe=key-directory" in args:
            probe(args)
        return
    if args[:2] == ["rm", "-f"] or args[0] == "port":
        sys.exit(0 if args[0] == "rm" else 1)
    sys.exit(0)


if __name__ == "__main__":
    main()
