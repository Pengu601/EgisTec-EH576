#!/usr/bin/env bash
#
# Build and install the EgisTec EH576 libfprint driver, and optionally wire it
# into fprintd/PAM for login.
#
#   ./install.sh              build + install the driver
#   ./install.sh --with-pam   also enable fingerprint login (asks first)
#   ./install.sh --uninstall  remove everything this script installed
#
# The driver installs to /usr/local, which precedes /usr/lib in the linker
# search path, so it takes precedence over the distribution's libfprint
# without overwriting a single packaged file. Uninstalling restores the
# distribution's library exactly.
#
set -euo pipefail

PREFIX=/usr/local
LIBDIR=lib/x86_64-linux-gnu
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIBFPRINT_DIR="$SRC_DIR/libfprint"
LIBFPRINT_GIT=https://gitlab.freedesktop.org/libfprint/libfprint.git

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
die()   { red "error: $*"; exit 1; }

need_root() {
  [ "$(id -u)" -eq 0 ] || die "this step needs root; re-run with sudo"
}

uninstall() {
  need_root
  rm -f "$PREFIX/$LIBDIR"/libfprint-2.so*
  rm -f "$PREFIX/$LIBDIR/pkgconfig/libfprint-2.pc"
  rm -rf "$PREFIX/include/libfprint-2"
  ldconfig
  green "Removed. The distribution's libfprint is active again:"
  ldconfig -p | grep libfprint-2.so.2 || true
  echo
  echo "If you enabled fingerprint login, disable it with:"
  echo "    sudo pam-auth-update --disable fprintd"
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall

bold "== checking the sensor =="
if lsusb -d 1c7a:0576 >/dev/null 2>&1; then
  green "found: $(lsusb -d 1c7a:0576)"
else
  red "No 1c7a:0576 device found. This driver is only for the EgisTec EH576."
  read -rp "Continue anyway? [y/N] " a; [ "$a" = y ] || exit 1
fi

bold "== checking build dependencies =="
missing=()
for pkg in meson ninja-build libgusb-dev libnss3-dev libgudev-1.0-dev \
           libglib2.0-dev pkg-config gcc; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if [ ${#missing[@]} -gt 0 ]; then
  red "missing packages: ${missing[*]}"
  echo "install them with:"
  echo "    sudo apt install ${missing[*]}"
  exit 1
fi
green "all present"

bold "== fetching libfprint =="
if [ -d "$LIBFPRINT_DIR/.git" ] || [ -f "$LIBFPRINT_DIR/meson.build" ]; then
  green "using existing tree at $LIBFPRINT_DIR"
else
  git clone --depth 1 "$LIBFPRINT_GIT" "$LIBFPRINT_DIR"
fi

bold "== adding the driver =="
cp "$SRC_DIR"/egis0576.c "$SRC_DIR"/egis0576.h \
   "$SRC_DIR"/egis_match.c "$SRC_DIR"/egis_match.h \
   "$LIBFPRINT_DIR/libfprint/drivers/"

# register in both meson files, idempotently
if ! grep -q "'egis0576'" "$LIBFPRINT_DIR/meson.build"; then
  sed -i "s/^\( *\)'egis0570': {},/\1'egis0570': {},\n\1'egis0576': {},/" \
      "$LIBFPRINT_DIR/meson.build"
fi
if ! grep -q "egis0576.c" "$LIBFPRINT_DIR/libfprint/meson.build"; then
  sed -i "s|^\( *\)'egis0570' : files('drivers/egis0570.c'),|\1'egis0570' : files('drivers/egis0570.c'),\n\1'egis0576' : files(\n\1    'drivers/egis0576.c',\n\1    'drivers/egis_match.c',\n\1),|" \
      "$LIBFPRINT_DIR/libfprint/meson.build"
fi
grep -q "'egis0576'" "$LIBFPRINT_DIR/meson.build" || die "could not register the driver in meson.build"

# upstream's tests/meson.build trips some meson versions
sed -i 's/^\( *\)foreach driver_test: drivers_tests$/\1foreach driver_test, driver_test_info: drivers_tests/' \
    "$LIBFPRINT_DIR/tests/meson.build" 2>/dev/null || true
green "registered"

bold "== building =="
cd "$LIBFPRINT_DIR"
[ -d build ] || meson setup build --prefix="$PREFIX" --libdir="$LIBDIR" \
    -Ddrivers=egis0576 -Ddoc=false -Dintrospection=false -Dgtk-examples=false
ninja -C build
green "built"

bold "== installing (needs root) =="
sudo meson install -C build
sudo ldconfig

RESOLVED=$(ldconfig -p | grep -m1 'libfprint-2.so.2 ' | awk '{print $NF}')
echo "libfprint-2.so.2 now resolves to: $RESOLVED"
case "$RESOLVED" in
  "$PREFIX"/*) green "OK - this build takes precedence" ;;
  *) die "the distribution's library still wins; $PREFIX/$LIBDIR may not be in your linker path" ;;
esac

if command -v fprintd-enroll >/dev/null 2>&1; then
  sudo systemctl stop fprintd 2>/dev/null || true
  green "fprintd found and restarted; it will load this driver on next use"
else
  red "fprintd is not installed - install it for login support:"
  echo "    sudo apt install fprintd libpam-fprintd"
fi

if [ "${1:-}" = "--with-pam" ]; then
  bold "== fingerprint login =="
  cat <<'WARN'
This enables fingerprint authentication for login, the lock screen and sudo.
Your password keeps working as a fallback.

Before saying yes, enrol and verify a finger first, and keep a root shell
open in another terminal while you test - a broken PAM stack is awkward to
recover from.
WARN
  read -rp "Enable fingerprint login now? [y/N] " a
  if [ "$a" = y ]; then
    sudo pam-auth-update --enable fprintd
    green "enabled - test with 'sudo -k && sudo true' in a NEW terminal before logging out"
  else
    echo "skipped; enable later with: sudo pam-auth-update --enable fprintd"
  fi
fi

echo
bold "== next steps =="
cat <<EOF
  fprintd-enroll     enrol a finger (vary its position across the 8 presses:
                     centred, tip, knuckle, left, right, roll left, roll right,
                     centred - coverage is what keeps false rejects low)
  fprintd-verify     test matching
  ./install.sh --uninstall     undo everything

Report results (scores and hardware, never raw fingerprint images) at:
  https://github.com/Pengu601/EgisTec-EH576
EOF
