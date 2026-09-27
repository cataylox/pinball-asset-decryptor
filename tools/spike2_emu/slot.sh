#!/bin/bash
# slot.sh - a rig slot's rootfs: mount it, unmount it, start it over.
#
#   slot.sh up N       mount slot N's overlay (root; once per WSL boot)
#   slot.sh down N     unmount it (root; refused while slot N has a run up)
#   slot.sh reset N    forget everything slot N wrote and start again from the
#                      ordinary rig (root; refused while a run is up)
#   slot.sh status     every slot: mounted or not, and what its upper layer holds
#
# What a slot IS lives in padpath.sh ("RIG SLOTS"). In one line: slot N's
# rootfs is ~/spike2root seen through an overlay whose writes land in
# ~/padslots/N/upper, so a slot costs only what it changes.
#
# Run as root through wsl.exe, from Windows:
#   wsl -u root -e bash <rig>/slot.sh up 2
. "$(dirname "$0")/padpath.sh"
set -u

die() { echo "slot: $*" >&2; exit 1; }
need_root() { [ "$(id -u)" = 0 ] || die "$1 takes root:  wsl -u root -e bash $0 $*"; }
slot_arg() {
    case "${1:-}" in ''|*[!0-9]*|0) die "a slot is a number from 1 to $PAD_SLOTS_MAX (slot 0 is the ordinary rig and has no overlay)" ;; esac
    [ "$1" -le "$PAD_SLOTS_MAX" ] || die "slot $1 is past PAD_SLOTS_MAX ($PAD_SLOTS_MAX)"
}
in_slot() { PAD_SLOT=$1 PAD_ROOT= PAD_TABLES= PAD_STAGE= PAD_LOGDIR= PAD_CARDS= bash -c ". '$RIG/padpath.sh'; $2"; }
busy() { [ "$(in_slot "$1" "bash '$RIG/alive.sh' --total")" != 0 ]; }

case "${1:-status}" in
    up)
        slot_arg "${2:-}"; need_root up "$2"
        in_slot "$2" pad_slot_ready ;;
    down)
        slot_arg "${2:-}"; need_root down "$2"
        busy "$2" && die "slot $2 still has rig processes - PAD_SLOT=$2 killgame.sh first"
        r=$PAD_HOME/padslots/$2/root
        mountpoint -q "$r" || { echo "slot $2 is not mounted"; exit 0; }
        umount "$r" && echo "slot $2 unmounted (its upper layer is kept)" ;;
    reset)
        slot_arg "${2:-}"; need_root reset "$2"
        busy "$2" && die "slot $2 still has rig processes - PAD_SLOT=$2 killgame.sh first"
        d=$PAD_HOME/padslots/$2
        mountpoint -q "$d/root" && { umount "$d/root" || die "could not unmount $d/root"; }
        rm -rf "$d/upper" "$d/work"
        in_slot "$2" pad_slot_ready && echo "slot $2 reset: it is the ordinary rig again" ;;
    status)
        printf '%-4s %-8s %s\n' SLOT MOUNTED "UPPER (what the slot changed)"
        for n in $(seq 1 "$PAD_SLOTS_MAX"); do
            d=$PAD_HOME/padslots/$n
            m=no; mountpoint -q "$d/root" 2>/dev/null && m=yes
            u=-; [ -d "$d/upper" ] && u=$(du -sh "$d/upper" 2>/dev/null | cut -f1)
            printf '%-4s %-8s %s\n' "$n" "$m" "$u"
        done ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
