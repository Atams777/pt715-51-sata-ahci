#!/usr/bin/env python3
"""Switch the Acer Predator PT715-51 (Insyde BIOS V1.10) SATA mode from RAID to AHCI
by changing one byte of the PchSetup UEFI variable.

  PchSetup  GUID 4570B7F1-ADE8-4943-8DC3-406472842384, size 0x661
  offset 0x42 "SATA Mode Selection": 0x0 = AHCI, 0x1 = RAID
  (from the IFR in BIOS_Acer_1.10_A_A.zip -> ZGL_110.exe -> SetupUtility)

This offset is only valid for this model and BIOS version. The script refuses
to run anywhere else. Do not edit the checks to make it run on other machines.

WARNING: after the switch, any Windows install on the internal drive(s) will not
boot, and a two-SSD RAID 0 array becomes unreadable. Back up anything you need first.

Usage:
  python3 set-sata-ahci.py                                    # dry run: checks everything, writes nothing
  sudo python3 set-sata-ahci.py --apply [--backup-dir DIR]    # back up, then write AHCI
  sudo python3 set-sata-ahci.py --restore FILE                # write a backup back unchanged

Recovery if the machine misbehaves: enter BIOS (F2) and Load Setup Defaults (F9),
which puts SATA mode back to RAID, or run --restore with the backup.
"""
import argparse
import datetime
import os
import subprocess
import sys

EFI_DIR = "/sys/firmware/efi"
EFIVARS = "/sys/firmware/efi/efivars"
VAR = EFIVARS + "/PchSetup-4570b7f1-ade8-4943-8dc3-406472842384"
ATTRS = bytes([0x07, 0x00, 0x00, 0x00])  # NV | BS | RT
DATA_SIZE = 0x661
OFFSET = 0x42
RAID, AHCI = 0x01, 0x00
EXPECTED = {  # DMI checks so this never runs on a different machine/firmware
    "/sys/class/dmi/id/product_name": "Predator PT715-51",
    "/sys/class/dmi/id/bios_vendor": "Insyde Corp.",
    "/sys/class/dmi/id/bios_version": "V1.10",
}
# Filesystems that do not survive a reboot (live USB sessions run from these).
VOLATILE_FS = {"tmpfs", "ramfs", "overlay", "squashfs", "aufs", "iso9660"}


def die(msg):
    sys.exit(f"ABORT: {msg}")


def read_var():
    try:
        with open(VAR, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        die(f"{VAR} does not exist. This firmware has no PchSetup variable, "
            "so it is not the BIOS this script was written for.")
    except PermissionError:
        die(f"cannot read {VAR}; try again with sudo")
    if len(raw) != 4 + DATA_SIZE:
        die(f"PchSetup is {len(raw) - 4:#x} bytes, expected {DATA_SIZE:#x}")
    if raw[:4] != ATTRS:
        die(f"PchSetup attributes are {raw[:4].hex()}, expected {ATTRS.hex()}")
    return raw


def write_var(raw):
    # efivarfs marks variables immutable; it requires attrs+data in a single write().
    subprocess.run(["chattr", "-i", VAR], check=True)
    try:
        fd = os.open(VAR, os.O_WRONLY)
        try:
            if os.write(fd, raw) != len(raw):
                die("short write; variable may be unchanged - re-run the dry run to check")
        except OSError as e:
            die(f"firmware rejected the write ({e.strerror}). The variable is locked; "
                "nothing was changed. A setup_var boot USB is the fallback.")
        finally:
            os.close(fd)
    finally:
        subprocess.run(["chattr", "+i", VAR], check=False)


def check_environment():
    if not os.path.isdir(EFI_DIR):
        die("this system was not booted in UEFI mode, so UEFI variables are not "
            "available. Boot the live USB in UEFI mode (not legacy/CSM) and try again.")
    if not os.path.isdir(EFIVARS) or not os.listdir(EFIVARS):
        die(f"efivarfs is not mounted. Mount it with: "
            f"sudo mount -t efivarfs efivarfs {EFIVARS}")
    for path, want in EXPECTED.items():
        try:
            with open(path) as f:
                got = f.read().strip()
        except OSError:
            die(f"cannot read {path}, so the machine model cannot be verified")
        if got != want:
            die(f"{path} is {got!r}, expected {want!r}. This script only works on "
                "an Acer Predator PT715-51 with BIOS V1.10.")
    print("Machine and BIOS version match.")


def fs_type(path):
    """Filesystem type of the mount that contains path."""
    path = os.path.realpath(path)
    best, best_type = "", None
    with open("/proc/self/mounts") as f:
        for line in f:
            _, mnt, typ = line.split()[:3]
            mnt = mnt.replace("\\040", " ")
            if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and len(mnt) > len(best):
                best, best_type = mnt, typ
    return best_type


def check_backup_dir(backup_dir):
    if not os.path.isdir(backup_dir):
        die(f"backup directory {backup_dir} does not exist")
    typ = fs_type(backup_dir)
    if typ in VOLATILE_FS:
        die(f"{backup_dir} is on {typ}, which is wiped at reboot (this looks like a live USB "
            "session). Pass --backup-dir pointing at a real disk, e.g. a mounted USB stick.")


def confirm():
    print()
    print("This switches SATA mode from RAID to AHCI. After rebooting:")
    print("  - any Windows install on the internal drive(s) will not boot")
    print("  - a two-SSD RAID 0 array will be unreadable")
    print("To undo: BIOS (F2) -> Load Setup Defaults (F9), or run --restore with the backup.")
    try:
        answer = input("Type YES to continue: ")
    except EOFError:
        answer = ""
    if answer.strip() != "YES":
        die("not confirmed; nothing was changed")


def apply(backup_dir):
    raw = read_var()
    cur = raw[4 + OFFSET]
    if cur == AHCI:
        print("SATA mode is already AHCI (0x0). Nothing to do.")
        return
    if cur != RAID:
        die(f"byte at {OFFSET:#x} is {cur:#x}, expected {RAID:#x} (RAID)")
    check_backup_dir(backup_dir)
    confirm()

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(os.path.abspath(backup_dir), f"PchSetup-backup-{stamp}.bin")
    with open(backup, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    if "SUDO_UID" in os.environ:  # leave the backup owned by the user, not root
        os.chown(backup, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    print(f"Backup written: {backup}")

    new = bytearray(raw)
    new[4 + OFFSET] = AHCI
    write_var(bytes(new))

    after = read_var()
    diffs = [i - 4 for i in range(len(raw)) if raw[i] != after[i]]
    if diffs != [OFFSET] or after[4 + OFFSET] != AHCI:
        die(f"verification failed, changed offsets: {[hex(d) for d in diffs]}. "
            f"Restore with: sudo python3 {sys.argv[0]} --restore {backup}")
    print("Verified: only offset 0x42 changed, now 0x0 (AHCI).")
    print("Reboot. Linux should then show the internal drive(s) as /dev/nvme*.")


def restore(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        die(f"cannot read {path}: {e.strerror}")
    if len(raw) != 4 + DATA_SIZE or raw[:4] != ATTRS:
        die(f"{path} does not look like a PchSetup backup")
    read_var()  # sanity-check the live variable still has the expected shape
    write_var(raw)
    if read_var() != raw:
        die("restore verification failed")
    print(f"Restored PchSetup from {path}. SATA mode byte = {raw[4 + OFFSET]:#x}. Reboot to take effect.")


def main():
    parser = argparse.ArgumentParser(
        description="Switch an Acer Predator PT715-51 (BIOS V1.10) from RAID to AHCI. "
                    "With no options, does a dry run.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="back up PchSetup, then write AHCI")
    mode.add_argument("--restore", metavar="FILE", help="write a backup back unchanged")
    parser.add_argument("--backup-dir", metavar="DIR",
                        default=os.path.dirname(os.path.abspath(__file__)),
                        help="where to save the backup (default: the script's folder); "
                             "must survive a reboot")
    args = parser.parse_args()

    check_environment()
    if args.restore:
        if os.geteuid() != 0:
            die("run with sudo")
        restore(args.restore)
    elif args.apply:
        if os.geteuid() != 0:
            die("run with sudo")
        apply(args.backup_dir)
    else:
        raw = read_var()
        cur = raw[4 + OFFSET]
        name = {RAID: "RAID", AHCI: "AHCI"}.get(cur, "UNKNOWN")
        print(f"PchSetup OK (size {DATA_SIZE:#x}, attrs {ATTRS.hex()}). Offset 0x42 = {cur:#x} ({name}).")
        print("Dry run only. To switch to AHCI: sudo python3 " + sys.argv[0] + " --apply")


if __name__ == "__main__":
    main()
