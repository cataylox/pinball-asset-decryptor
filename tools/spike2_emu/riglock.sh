#!/bin/bash
# riglock.sh - who holds which rig slot. The lock a session takes before it
# builds, runs, stops or mutates anything in a rig.
#
#   riglock.sh take --any <who> [what...]       first free slot >= 1; prints slot=N
#   riglock.sh take --slot N <who> [what...]    that slot or nothing
#   riglock.sh note N <what...>                 say what you are doing now
#   riglock.sh release N [<who>]                give it back (refused while a run is up)
#   riglock.sh list [--json]                    every slot: holder, doing, age, run
#   riglock.sh free                             the first free slot >= 1, or exit 1
#
# <who> names the holder the way every window of its run will: the item branch
# (item/48), the triage ticket (PAD-231) or the feature branch. <what> is a few
# words for what is UP right now - "godzilla run", "build", "app" - because
# that is what the next session and David's dashboard need to read.
#
# RUN IT AS ROOT TO TAKE A SLOT >= 1 (`wsl -u root -e bash riglock.sh take
# ...`): taking the slot also mounts its rootfs, which is an overlay and needs
# root (see padpath.sh, "RIG SLOTS"). As the plain user it still takes the
# lock and prints the one line that mounts the slot.
#
# THE RECORDS ARE ON THE WINDOWS SIDE (%USERPROFILE%\.pad-rig\slot-N.lock) so
# the app, the triage dashboard and a rig in any WSL distro all read the same
# ones - see pad_board_dir. Creation is `set -C` (O_EXCL), atomic on drvfs as
# on ext4: two sessions racing for one slot get one winner and one refusal.
#
# SLOT 0 IS THE ORDINARY RIG (~/spike2root), and the pre-slot lock file
# /home/<user>/.pad_rig_lock still means "slot 0 is held". Sessions that
# predate slots only know that file, so a slot 0 take writes both and a slot
# 0 listing reads both.
. "$(dirname "$0")/padpath.sh"
set -u

BOARD=$(pad_board_dir)
LEGACY=$PAD_HOME/.pad_rig_lock
# A run record older than this without a heartbeat is a run that died hard.
RUN_FRESH=${PAD_RUN_FRESH:-120}

die() { echo "riglock: $*" >&2; exit 1; }
clean() { printf '%s' "$*" | tr -d '"\\\r\n' | tr -cd '[:print:]' | cut -c1-80; }
now() { date +%s; }
lockf() { echo "$BOARD/slot-$1.lock"; }
runf() { echo "$BOARD/slot-$1.run"; }
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }   # GNU, then BSD/macOS

valid_slot() {
    case "$1" in ''|*[!0-9]*) die "not a slot number: '$1'" ;; esac
    [ "$1" -le "$PAD_SLOTS_MAX" ] || die "slot $1 is past this machine's $PAD_SLOTS_MAX (PAD_SLOTS_MAX)"
}

# Is a run up in slot N? Two witnesses, because each is blind somewhere: the
# board's run record (heartbeat) sees a run in ANY distro and one started as
# root, which this account may not be able to see in /proc; alive.sh sees a
# run that died without its teardown and left processes behind.
run_up() {
    local f
    f=$(runf "$1")
    if [ -f "$f" ] && [ $(( $(now) - $(mtime "$f") )) -lt "$RUN_FRESH" ]; then
        return 0
    fi
    [ "$(PAD_SLOT=$1 bash "$RIG/alive.sh" --total 2>/dev/null || echo 0)" != 0 ]
}

write_lock() {                    # <slot> <who> <what> <taken> -> stdout JSON
    printf '{"slot":%s,"who":"%s","what":"%s","distro":"%s","user":"%s","taken":%s}\n' \
        "$1" "$2" "$3" "$(clean "${WSL_DISTRO_NAME:-$(uname -n)}")" \
        "$(clean "${SUDO_USER:-$(id -un 2>/dev/null)}")" "$4"
}

held() {                          # <slot> -> 0 if held (any form)
    [ -f "$(lockf "$1")" ] && return 0
    [ "$1" = 0 ] && [ -f "$LEGACY" ] && return 0
    return 1
}

take_one() {                      # <slot> <who> <what>
    local f t
    f=$(lockf "$1")
    t=$(now)
    held "$1" && return 1
    # shellcheck disable=SC2094
    if ! ( set -C; write_lock "$1" "$2" "$3" "$t" > "$f" ) 2>/dev/null; then
        return 1
    fi
    if [ "$1" = 0 ]; then
        # The pre-slot protocol's file, same atomic create. Losing THAT race
        # means an old-protocol session got slot 0 first: give ours back.
        if ! ( set -C; echo "$2 $3" > "$LEGACY" ) 2>/dev/null; then
            rm -f "$f"
            return 1
        fi
        pad_give_back "$LEGACY"
    fi
    return 0
}

mount_hint() {
    local n=$1
    [ "$n" = 0 ] && return 0
    if [ "$(id -u)" = 0 ]; then
        PAD_SLOT=$n bash -c ". '$RIG/padpath.sh'; pad_slot_ready" || return 1
    elif ! mountpoint -q "$PAD_HOME/padslots/$n/root" 2>/dev/null; then
        echo "riglock: slot $n is yours but not mounted yet. Mount it (root, once per WSL boot):" >&2
        echo "  wsl -u root -e bash $RIG/slot.sh up $n" >&2
    fi
}

cmd_take() {
    local slot="" who what n
    case "${1:-}" in
        --any) shift ;;
        --slot) valid_slot "${2:-}"; slot=$2; shift 2 ;;
        *) die "take needs --any or --slot N" ;;
    esac
    who=$(clean "${1:-}")
    [ -n "$who" ] || who=$(pad_label)
    [ -n "$who" ] || die "take needs <who>: the item, ticket or branch this is for"
    shift || true
    what=$(clean "${*:-}")
    mkdir -p "$BOARD" || die "cannot create the board at $BOARD"
    if [ -n "$slot" ]; then
        take_one "$slot" "$who" "$what" || { cmd_show "$slot" >&2; die "slot $slot is held"; }
        echo "slot=$slot"
        mount_hint "$slot"
        return
    fi
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        if take_one "$n" "$who" "$what"; then
            echo "slot=$n"
            mount_hint "$n"
            return
        fi
    done
    cmd_list >&2
    die "every slot 1..$PAD_SLOTS_MAX is held"
}

cmd_note() {
    local n=${1:-} f who taken
    valid_slot "$n"
    shift
    f=$(lockf "$n")
    [ -f "$f" ] || die "slot $n is not held"
    who=$(pad_board_field "$f" who)
    taken=$(pad_board_field "$f" taken)
    write_lock "$n" "$who" "$(clean "$*")" "${taken:-$(now)}" > "$f.tmp" && mv -f "$f.tmp" "$f"
    [ "$n" = 0 ] && [ -f "$LEGACY" ] && echo "$who $(clean "$*")" > "$LEGACY"
    return 0
}

cmd_release() {
    local n=${1:-} who=${2:-} f cur force=0
    [ "${3:-}" = --force ] && force=1
    [ "$who" = --force ] && { force=1; who=; }
    valid_slot "$n"
    f=$(lockf "$n")
    cur=$(pad_board_field "$f" who)
    if [ -n "$who" ] && [ -n "$cur" ] && [ "$(clean "$who")" != "$cur" ]; then
        die "slot $n is held by '$cur', not '$who' - release only your own"
    fi
    if [ "$force" = 0 ] && run_up "$n"; then
        die "a run is still up in slot $n - stop it first (PAD_SLOT=$n killgame.sh), or --force"
    fi
    rm -f "$f"
    [ "$n" = 0 ] && rm -f "$LEGACY"
    echo "released slot $n"
}

age() {                           # seconds -> "5s" "12m" "3h"
    local s=$1
    if [ "$s" -lt 60 ]; then echo "${s}s"
    elif [ "$s" -lt 3600 ]; then echo "$((s / 60))m"
    else echo "$((s / 3600))h$(( (s % 3600) / 60 ))m"; fi
}

cmd_show() {                      # one human line for slot N
    local n=$1 f r who what t lage run="-" game rt st
    f=$(lockf "$n"); r=$(runf "$n"); t=$(now)
    who=$(pad_board_field "$f" who); what=$(pad_board_field "$f" what)
    if [ -z "$who" ] && [ "$n" = 0 ] && [ -f "$LEGACY" ]; then
        who=$(cut -d' ' -f1 < "$LEGACY"); what=$(cut -d' ' -f2- < "$LEGACY"); f=$LEGACY
    fi
    if [ -f "$r" ]; then
        game=$(pad_board_field "$r" game)
        rt=$(( t - $(mtime "$r") ))
        st=$(pad_board_field "$r" started)
        if [ "$rt" -lt "$RUN_FRESH" ]; then run="$game up $(age $(( t - ${st:-$t} )))"
        else run="$game STALE (no heartbeat for $(age "$rt"))"; fi
    fi
    if [ -n "$who" ]; then lage=$(age $(( t - $(mtime "$f") ))); else lage=""; who="(free)"; fi
    printf '%-4s %-22s %-24s %-6s %s\n' "$n" "$who" "${what:-}" "$lage" "$run"
}

cmd_list() {
    local n
    if [ "${1:-}" = --json ]; then
        printf '{"board":"%s","max":%s,"now":%s,"slots":[' "$BOARD" "$PAD_SLOTS_MAX" "$(now)"
        for n in $(seq 0 "$PAD_SLOTS_MAX"); do
            [ "$n" = 0 ] || printf ','
            printf '{"slot":%s,"lock":%s,"lock_mtime":%s,"run":%s,"run_mtime":%s}' "$n" \
                "$( [ -f "$(lockf "$n")" ] && tr -d '\n' < "$(lockf "$n")" || echo null)" \
                "$(mtime "$(lockf "$n")")" \
                "$( [ -f "$(runf "$n")" ] && tr -d '\n' < "$(runf "$n")" || echo null)" \
                "$(mtime "$(runf "$n")")"
        done
        echo ']}'
        return
    fi
    printf '%-4s %-22s %-24s %-6s %s\n' SLOT HOLDER DOING HELD RUN
    for n in $(seq 0 "$PAD_SLOTS_MAX"); do cmd_show "$n"; done
}

cmd_free() {
    local n
    for n in $(seq 1 "$PAD_SLOTS_MAX"); do
        held "$n" || { echo "$n"; return 0; }
    done
    return 1
}

case "${1:-}" in
    take) shift; cmd_take "$@" ;;
    note) shift; cmd_note "$@" ;;
    release) shift; cmd_release "$@" ;;
    list|"") shift || true; cmd_list "$@" ;;
    show) valid_slot "${2:-}"; cmd_show "$2" ;;
    free) cmd_free ;;
    *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
