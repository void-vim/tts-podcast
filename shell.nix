{ pkgs ? import <nixpkgs> {} }:

# Fast path: prebuilt PyPI wheels via uv (no source compile).
# nixpkgs over-specifies csvw->frictionless->aiokafka->cramjam (Rust) and
# frictionless->scipy (Fortran); pip installs kokoro-onnx's REAL deps, which
# avoid that whole chain. espeak-ng + ffmpeg still come from nix for offline use.
pkgs.mkShell {
  name = "tts-story-podcast-kokoro";
  buildInputs = [
    pkgs.uv
    pkgs.python312
    pkgs.stdenv.cc.cc.lib
    pkgs.portaudio
    pkgs.espeak-ng
    pkgs.ffmpeg
  ];
  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.portaudio}/lib:$LD_LIBRARY_PATH"
    export KOKORO_ESPEAK_LIB="${pkgs.espeak-ng}/lib/libespeak-ng.so"
    export KOKORO_ESPEAK_DATA="${pkgs.espeak-ng}/share/espeak-ng-data"
    export PHONEMIZER_ESPEAK_LIBRARY="${pkgs.espeak-ng}/lib/libespeak-ng.so"

    if [ ! -d .venv ]; then
      uv venv --python ${pkgs.python312}/bin/python .venv
      uv pip install --python .venv/bin/python \
        kokoro-onnx espeakng-loader sounddevice soundfile numpy onnxruntime phonemizer
    fi
    source .venv/bin/activate
  '';
}
