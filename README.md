# Switch an Acer Predator PT715-51 from RAID to AHCI

Linux can't see the internal NVMe SSD(s) on the Acer Predator Triton 700 (PT715-51),
because the SATA controller ships in Intel RST "RAID" mode. The kernel log shows:

```
ahci 0000:00:17.0: Found 1 remapped NVMe devices.
ahci 0000:00:17.0: Switch your BIOS from RAID to AHCI mode to use them.
```

The BIOS shows a "SATA Mode" option but it's greyed out, and Acer never released an update
to unlock it. The greyed-out option only locks the menu. The setting itself is an ordinary UEFI
variable that Linux can write. `set-sata-ahci.py` changes that one byte.

## Does this apply to you?

Only if **all** of these are true:

- The laptop is an **Acer Predator PT715-51**.
- The BIOS version is **V1.10** (Insyde). It's shown on the BIOS Main page, or run
  `cat /sys/class/dmi/id/bios_version`.
- You're booting Linux in **UEFI** mode, not legacy/CSM.

The script checks all of these and refuses to run otherwise. **Don't remove those checks.** The byte
it changes (offset `0x42` of `PchSetup`) was found in the V1.10 firmware's setup menu data. On any
other model or BIOS version, the same byte can control something else, and writing it can stop the
machine from booting.

## Before you start: what you lose

After the switch:

- **Windows on the internal drive(s) won't boot.** It was installed with the RST driver.
- **If your laptop has two SSDs in RAID 0** (a common factory setup), the array is broken and its
  data can't be read. Back up anything you want to keep **before** switching.

Once in AHCI mode, the SSD(s) appear in Linux as normal `/dev/nvme0n1` (and `/dev/nvme1n1`) devices
that you can partition and format.

## Steps

You'll usually run this from a **live USB** (for example Ubuntu or Pop!_OS), since the internal
drive isn't usable yet.

1. **Copy the script to a USB stick or external drive**, not the live session's home folder. The
   live session is erased on reboot, and the script saves its backup next to itself by default.
   The script refuses to save a backup to a location that won't survive a reboot.
   To download it straight onto a mounted USB stick:

   ```
   cd /media/$USER/<usb-stick>
   wget https://raw.githubusercontent.com/Atams777/pt715-51-sata-ahci/main/set-sata-ahci.py
   ```

   Run the remaining steps from that folder.

2. **Dry run** (changes nothing):

   ```
   python3 set-sata-ahci.py
   ```

   You should see:

   ```
   Machine and BIOS version match.
   PchSetup OK (size 0x661, attrs 07000000). Offset 0x42 = 0x1 (RAID).
   ```

3. **Apply:**

   ```
   sudo python3 set-sata-ahci.py --apply
   ```

   If the script is on the live session's filesystem, pass a real disk for the backup:
   `--backup-dir /media/<you>/<usb-stick>`.

   The script:
   - stops unless the byte currently reads `0x1` (RAID)
   - asks you to type `YES`
   - saves the whole variable to `PchSetup-backup-<timestamp>.bin`
   - writes `0x0` (AHCI) to that single byte
   - re-reads the variable and confirms no other byte changed

4. **Reboot**, then check that the drive appears:

   ```
   lsblk
   ```

   Look for `nvme0n1`. If the kernel log still shows "remapped NVMe devices", the setting didn't
   stick (see Troubleshooting below).

**Keep the backup file.** You need it for `--restore`.

## Undoing it

Either of these puts the laptop back in RAID mode:

- **BIOS:** press F2 at boot, then **Load Setup Defaults (F9)**, then save and exit.
- **Script:** `sudo python3 set-sata-ahci.py --restore PchSetup-backup-<timestamp>.bin`, then reboot.

## Troubleshooting

| Message | Meaning |
|---|---|
| `this system was not booted in UEFI mode` | Reboot and choose the UEFI entry for your USB stick in the boot menu (F12). |
| `efivarfs is not mounted` | Run the `mount` command the script prints, then try again. |
| `.../bios_version is 'V1.0x', expected 'V1.10'` | Update to V1.10 from Acer's support site first. Don't use the script on other versions. |
| `firmware rejected the write` | The firmware locked the variable. Nothing changed. The fallback is booting a `setup_var` EFI tool and setting `PchSetup` offset `0x42` to `0x0`. |
| Drive still missing after reboot | The firmware may reset the value at boot. Run the dry run again: if it reads `0x1`, the firmware changed it back. |
| Laptop stops at the BIOS or won't boot | Press F2, load defaults (F9), save and exit. |

## Where the offset comes from

Acer's V1.10 package (`BIOS_Acer_1.10_A_A.zip`) contains `ZGL_110.exe`, an Insyde flash tool with
the firmware image embedded in it. Its `SetupUtility` module has the setup menu data (IFR). The IFR
defines **"SATA Mode Selection"** in Intel's hidden "SATA And RST Configuration" menu:

- Variable: `PchSetup`, GUID `4570B7F1-ADE8-4943-8DC3-406472842384`, VarStoreId 0x5, size 0x661
- Offset `0x42`, 1 byte: `0x0` = AHCI, `0x1` = RAID (default)

It's the only SATA mode setting in the image. Acer's visible "SATA Mode" item is display-only.

## Status

**Tested on one laptop** (PT715-51, BIOS V1.10, single 512 GB LITEON SSD), where it worked: the
internal SSD appeared as `nvme0n1` after one reboot. The two-SSD RAID 0 setup hasn't been tested.
Use at your own risk. Released under the MIT License (see `LICENSE`).
