#!/bin/sh
# One-off: create the GitHub repo, milestones, labels and the initial issues.
# Needs the GitHub CLI (gh) logged in. Run from the repository root:
#   .github/bootstrap-github.sh <repo-name> <public|private>
set -eu

NAME=${1:?usage: $0 <repo-name> <public|private>}
VIS=${2:?usage: $0 <repo-name> <public|private>}

gh repo create "$NAME" "--$VIS" --source . --remote origin \
  --description "DIY 3-phase power analyzer (ATM90E36 + Pico) with a Clockwork uConsole as host"
git push -u origin HEAD
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

for m in "v0.1-pzem-poc|PZEM-004T + CP2102 proof of concept on the uConsole" \
         "v0.2-pihat-alive|ATM90E36 on the PiHat Lite answers the Pico over SPI" \
         "v0.3-pico-usb-link|Pico streams measurements to the uConsole over USB"; do
  gh api "repos/$REPO/milestones" -f title="${m%%|*}" -f description="${m#*|}" >/dev/null
done

gh label create question  --color d876e3 --description "Open design question" --force
gh label create hardware  --color 0e8a16 --description "Hardware" --force
gh label create firmware  --color 1d76db --description "Pico firmware" --force
gh label create host      --color 5319e7 --description "uConsole software" --force
gh label create safety    --color b60205 --description "Safety relevant" --force
gh label create later     --color c5def5 --description "Not planned for now" --force

gh issue create --title "Box power source: uConsole USB or separate 230V/5V supply?" \
  --label question,hardware,safety --milestone v0.3-pico-usb-link --body '
The front-end box (PiHat + Pico + transformers) needs power. Options:

**A: from the uConsole over the USB link**
- one cable, no extra mains-connected supply in the box
- uConsole battery drain; ground of the box tied to the uConsole
- an isolated USB link would need an isolated DC/DC as well

**B: separate 230V/5V supply in the box**
- independent of the uConsole battery; box can run alone
- another mains-connected part in the box; must be a SELV/safety-isolated type
- USB link then connects two separately powered grounds (ground loop?)

To decide: measure box current draw, check uConsole USB budget, test noise on
both options.

See docs/design/0003-wired-usb-link.md and docs/design/0004-isolated-front-end-box.md.'

gh issue create --title "Test the 230V/9V voltage transformers" \
  --label question,hardware,safety --milestone v0.2-pihat-alive --body '
Before relying on the small 230V/9V transformers for voltage sensing, measure:

- [ ] datasheet: safety-isolating (EN 61558-2-6), insulation class, test voltage
- [ ] ratio at no load and with the actual input load of the PiHat
- [ ] linearity over roughly 180V-260V input
- [ ] phase shift primary vs secondary at 50Hz (needed for calibration)
- [ ] waveform distortion / harmonic response
- [ ] temperature drift after warm-up
- [ ] insulation test primary-secondary (500V DC)

Record raw data in measurements/raw/ and a journal entry.'

gh issue create --title "Protocol between Pico and uConsole" \
  --label question,firmware,host --milestone v0.3-pico-usb-link --body '
Define how the Pico sends measurements (and receives commands/calibration) over USB.

Questions:
- USB CDC serial vs custom/vendor class
- text (line-based, JSON) vs binary framing (e.g. COBS + CRC)
- versioning of the message format
- sample rate / what is sent: RMS values, power, energy, harmonics, waveforms?
- commands: read/write calibration registers, set rate, firmware version
- recovery after disconnect, noise, partial frames
- timestamps

Must be robust against industrial noise (see docs/design/0003-wired-usb-link.md).'

gh issue create --title "ATM90E36 calibration procedure" \
  --label question,firmware --body '
Turn the outline in docs/calibration.md into a tested procedure:

- [ ] collect datasheet and application note into hardware/datasheets/
- [ ] verify register groups and checksum handling (CS0-CS3)
- [ ] choose reference meter and test loads
- [ ] offset calibration
- [ ] voltage/current gain per phase
- [ ] phase compensation for transformers and CTs (PF=0.5)
- [ ] verification table and storage of calibration values
- [ ] tooling on the host to run the calibration'

gh issue create --title "Rogowski coils (later)" --label later,hardware --body '
Iron-core split CTs are used for now (docs/design/0002-split-cts-vs-rogowski.md).
Rogowski coils would remove saturation and size limits and improve bandwidth.

To find out when the time comes:
- does the ATM90E36 support Rogowski input / digital integration, or is an
  external integrator needed?
- which coils (output level, accuracy, position sensitivity)
- how to calibrate and switch between CT and Rogowski per channel'

# Simple project board (needs: gh auth refresh -s project)
if gh project create --owner "@me" --title "3-phase power analyzer" >/dev/null 2>&1; then
  echo "Project board created. Link it to the repo and add issues from the web UI or with 'gh project item-add'."
else
  echo "Project board skipped (run 'gh auth refresh -s project' and create it manually if wanted)."
fi
