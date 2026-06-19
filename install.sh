#!/bin/bash
# Installs the `sim` command globally so you can run any .ino from anywhere.
# Usage: bash install.sh

EMULATOR_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="/usr/local/bin/sim"

cat > "$WRAPPER" <<EOF
#!/bin/bash
python3 "$EMULATOR_DIR/sim.py" "\$@"
EOF

chmod +x "$WRAPPER"
echo "Installed: sim → $WRAPPER"
echo ""
echo "You can now run from anywhere:"
echo "  sim path/to/firmware.ino --pin 2=LED --led LED"
