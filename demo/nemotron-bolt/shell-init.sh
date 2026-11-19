# Chief-of-staff demo: make Hermes terminal commands in this profile find the
# demo's Python (the system `python` is the Microsoft Store stub) and the
# profile's own home, where the skills and Google token live.
export HERMES_HOME='C:\Users\NVIDIA\AppData\Local\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff'
case ":$PATH:" in
  *":/c/Users/NVIDIA/chief-of-staff-runtime/python:"*) ;;
  *) export PATH="/c/Users/NVIDIA/chief-of-staff-runtime/python:$PATH" ;;
esac
# Hermes Desktop's own library path must not leak into the demo's Python:
# its bundled Google/cryptography libraries cannot be loaded from outside the app.
unset PYTHONPATH PYTHONHOME
