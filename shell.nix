{ pkgs ? import <nixpkgs> {} }:

# Fast path: prebuilt PyPI wheels via uv (no source compile).
# nixpkgs over-specifies heavy native chains; pip installs Chatterbox's REAL
# deps (torch, etc.) as wheels. espeak-ng + ffmpeg + zlib come from nix for
# runtime library resolution.
pkgs.mkShell {
  name = "tts-story-podcast-chatterbox";
  buildInputs = [
    pkgs.uv
    pkgs.python312
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
    pkgs.portaudio
    pkgs.espeak-ng
    pkgs.ffmpeg
  ];
  shellHook = ''
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib:${pkgs.portaudio}/lib:$LD_LIBRARY_PATH"

    if [ ! -d .venv ]; then
      uv venv --python ${pkgs.python312}/bin/python .venv
      uv pip install --python .venv/bin/python \
        chatterbox-tts soundfile torchaudio
    fi
    source .venv/bin/activate

    # Pre-fetch Chatterbox model weights into the HF cache (cached; fast on re-entry)
    python3 -c "from huggingface_hub import snapshot_download; snapshot_download('ResembleAI/chatterbox')" || true
  '';
}
